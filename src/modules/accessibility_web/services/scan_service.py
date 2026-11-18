"""
scan_service.py - Service layer for the web_accessibility_scans resource.

scan_service.create_scan()
        |
        +-- Load website (WebAccessibilityWebsiteModel); 404 if missing
        +-- Reject if url's host isn't the website's base_url host or a
        |   subdomain of it (SSRF: a scan can only ever target the site
        |   it was registered against - see acquisition/url_guard.py)
        +-- Get-or-create the Page this url belongs to (_get_or_create_page -
        |   Website 1:N Page 1:N Scan 1:N Issue, see
        |   web_accessibility_pages_model.py). A page persists across scans;
        |   this is what lets run_scan() dedup issues by page instead of by
        |   scan (see "Issue lifecycle / dedup" below).
        +-- Create web_accessibility_scans record, status=QUEUED, page_id set
        +-- Return scan (caller hands scan.id to a background task)

scan_service.run_scan()                         <-- separate method, called
        |                                           as a FastAPI BackgroundTask
        +-- Load the scan, flip status -> RUNNING, stamp started_at
        +-- Fetch the URL via acquisition.url_guard.safe_fetch() - not a bare
        |   requests.get(): validates scheme, DNS-resolves and rejects
        |   private/reserved-range addresses (with a config allowlist for
        |   deliberate internal targets), and re-validates every redirect
        |   hop the same way, before this scan status can become BLOCKED
        |   instead of RUNNING -> COMPLETED
        +-- Parse the response body (_AccessibilityHTMLParser, stdlib only -
        |   this reads the raw HTML the server returned; it does not run
        |   JavaScript / render like a browser would - no headless-browser
        |   dependency is installed in this project)
        +-- Evaluate parsed elements against RULE_CHECKS
        +-- Upsert findings into WebAccessibilityIssuesModel (_upsert_issue) -
        |   NOT a blind insert. A finding is deduped against any existing
        |   issue for the same (page_id, rule, element_selector); a match
        |   bumps times_seen/last_seen_scan_id instead of creating a second
        |   row for the same underlying defect. Any previously-OPEN issue
        |   for this page that this scan did NOT re-find gets marked
        |   RESOLVED (_resolve_stale_issues) - it's a scan-over-scan history
        |   of persistent defects, not a fresh issue list every run.
        +-- Roll status -> COMPLETED (or FAILED on a network error, or
            BLOCKED if url_guard rejected the URL/a redirect target),
            stamp completed_at, total_issues, accessibility_score

Page model: a Page (web_accessibility_pages) is the persistent entity a
URL represents on a website - Website 1:N Page 1:N Scan 1:N Issue. It's
what issue dedup is actually scoped to (page_id, not website+url string
matching - see _upsert_issue/_resolve_stale_issues). Created implicitly
by _get_or_create_page() the first time a URL is scanned - by a manual
POST .../scan, or by crawl_website() below. See PageService
(page_service.py) for the read-only GET /pages/{id}/scans endpoint.
Existing scans/issues from before this migration need
scripts/migrate_web_accessibility_pages.py to get a real page_id.

crawl_website() (POST /websites/{id}/scan, all_pages=true): discovers a
website's pages (sitemap-first, falling back to single-level homepage
link-scraping - see crawl_website()'s own docstring below for the two
methods and why), then calls create_scan() once per discovered URL,
bounded by max_pages (default DEFAULT_CRAWL_MAX_PAGES=20, hard-capped at
HARD_MAX_CRAWL_PAGES=100 regardless of what's requested). This is how a
website with several pages gets more than one Page/Scan without the
caller having to already know and POST every individual page URL by
hand - each discovered page is scanned exactly like any manually-queued
scan (same SSRF checks, same issue dedup). Unlike a single create_scan()
call, this DOES write one row of its own first: a WebAccessibilityCrawlsModel
("crawl run" - see web_accessibility_crawls_model.py), and every scan it
then queues gets that crawl's id in its own crawl_id column. That's what
lets GET /scans/crawl-{id} return every discovered page's result (issues
included) as ONE response, page-wise, instead of the caller polling each
page's scan_id one at a time - see web_accessibility_router.py's
get_scan(). A manually-queued single scan (all_pages omitted/false) has
no crawl - its crawl_id stays NULL, and GET /scans/{scan_id} (a plain
integer, not "crawl-...") returns just that one page's result+issues.

Issue lifecycle / dedup: web_accessibility_issues rows are persistent
defects, not per-scan snapshots - re-scanning a page that still has the
same problem does NOT insert a new row every time. See _upsert_issue()
and _resolve_stale_issues() below, and the class docstring on
WebAccessibilityIssuesModel. Status transitions: OPEN on first detection;
RESOLVED once a scan of the same page stops finding it; REOPENED (not a
fresh OPEN row) if a RESOLVED issue is found again later - so a dashboard
can distinguish "still open since first seen" from "was fixed, regressed"
- and back to RESOLVED if it goes away again. OPEN and REOPENED both count
as currently-open (_OPEN_ISSUE_STATUSES) everywhere that matters: scoring,
accessibility_status, and _resolve_stale_issues' "still open" query.
GET /scans/{scan_id} embeds issues where THIS scan either
originally created them (scan_id, permanent - a scan keeps showing what it
found even after a later scan reconfirms the same issue) OR most recently
reconfirmed them (last_seen_scan_id, current state - times_seen/status/
resolved_at always reflect the latest scan, not a frozen snapshot from
when the row was created). Exact per-scan-run history (which scans,
plural, found a given issue, and in what state at that moment) isn't
tracked - only first-seen/last-seen/times_seen. That's a deliberate
simpler alternative to a full issue+occurrence join table.

run_scan() also rolls the *website's* accessibility_status:
    SCANNING while this run is in flight, then PASS/WARNING/FAIL from the
    findings on COMPLETED, or reverted to whatever it was before this run
    started if the scan ends BLOCKED/FAILED (no real assessment happened).
    See _derive_accessibility_status(). This is the only writer of that
    field - website_schema.WebsiteUpdate deliberately excludes it so a
    client can't PUT an arbitrary status without an actual scan.

Sits between web_accessibility_router.py and:
    WebAccessibilityScansModel   – scans (create_scan + run_scan both write here)
    WebAccessibilityCrawlsModel  – one row per all_pages=true request; every
                                    scan it queues carries that row's id as
                                    its own crawl_id (see crawl_website())
    WebAccessibilityWebsiteModel – to validate website_id + the url-guard domain
                                    check, and to roll up accessibility_status
    WebAccessibilityPagesModel   – get-or-created per (website_id, url); scans
                                    and issues both key their dedup off page_id
    WebAccessibilityIssuesModel  – findings run_scan() writes
    WebAccessibilityRulesModel   – rule metadata findings are linked to
    acquisition/url_guard.py     – SSRF-safe fetch used instead of bare requests.get()
"""

import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from decimal import Decimal
from html.parser import HTMLParser
from typing import Optional
from urllib.parse import urldefrag, urljoin, urlsplit

import requests
from sqlalchemy import or_
from sqlalchemy.orm import Session

from src.core.database import SessionLocal
from src.core.logger import get_logger
from src.modules.accessibility_web.acquisition.url_guard import (
    UrlGuardError,
    safe_fetch,
    same_domain_or_subdomain,
)
from src.modules.accessibility_web.models.web_accessibility_crawls_model import (
    WebAccessibilityCrawlsModel,
)
from src.modules.accessibility_web.models.web_accessibility_issues_model import (
    WebAccessibilityIssuesModel,
)
from src.modules.accessibility_web.models.web_accessibility_pages_model import (
    WebAccessibilityPagesModel,
    hash_page_url,
)
from src.modules.accessibility_web.models.web_accessibility_rules_model import (
    WebAccessibilityRulesModel,
)
from src.modules.accessibility_web.models.web_accessibility_scans_model import (
    WebAccessibilityScansModel,
)
from src.modules.accessibility_web.models.web_accessibility_websites_model import (
    WebAccessibilityWebsiteModel,
)

logger = get_logger(__name__)

FETCH_TIMEOUT_SECONDS = 15
USER_AGENT = "OrionAccessibilityBot/1.0 (+web accessibility scanner)"
MAX_SNIPPET_LENGTH = 65000  # headroom under MySQL TEXT's ~65535-byte cap

# ScanService.crawl_website() page-count caps - see its docstring.
DEFAULT_CRAWL_MAX_PAGES = 20
HARD_MAX_CRAWL_PAGES = 100

_SEVERITY_PENALTY = {"CRITICAL": 15, "SERIOUS": 10, "MODERATE": 5, "MINOR": 2}
_DEFAULT_PENALTY = 5

# website.accessibility_status values this module writes. UNKNOWN is the
# model's column default for a never-scanned website; the rest are set
# below by run_scan()/​_derive_accessibility_status() only - never by a
# client-supplied WebsiteUpdate (see website_schema.py).
_FAILING_SEVERITIES = {"CRITICAL", "SERIOUS"}

# web_accessibility_issues.status values that mean "still a live problem" -
# both count as open for _resolve_stale_issues() and anywhere else that
# needs "is this issue currently affecting the page".
_OPEN_ISSUE_STATUSES = {"OPEN", "REOPENED"}

# Rule rows for the checks implemented below. There's no seed script /
# CRUD for web_accessibility_rules yet, so run_scan() get-or-creates these
# on demand rather than leaving the checks permanently unable to record
# findings (rule_id is a real FK - it needs a row to point at). Move this
# to a proper seed migration once one exists.
_DEFAULT_RULES = [
    {
        "rule_code": "IMG-001",
        "name": "Images must have alternative text",
        "wcag_criterion": "1.1.1",
        "wcag_level": "A",
        "category": "IMAGES",
        "severity": "CRITICAL",
    },
    {
        "rule_code": "FORM-001",
        "name": "Form controls must have accessible labels",
        "wcag_criterion": "1.3.1",
        "wcag_level": "A",
        "category": "FORMS",
        "severity": "SERIOUS",
    },
]

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


class _AccessibilityHTMLParser(HTMLParser):
    """
    Minimal structural parser: collects just enough from the raw HTML
    response body for RULE_CHECKS to evaluate. Not a browser - no CSS, no
    JS, no layout.
    """

    _LABELABLE_TAGS = {"input", "select", "textarea"}
    _SKIP_INPUT_TYPES = {"hidden", "submit", "button", "reset", "image"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.images: list[dict] = []
        self.form_controls: list[dict] = []
        self.label_for_ids: set[str] = set()
        self.links: list[str] = []  # raw href values of every <a href> seen - see crawl_website()
        self._label_depth = 0

    def handle_starttag(self, tag, attrs_list):
        attrs = dict(attrs_list)
        snippet = self._reconstruct(tag, attrs_list)

        if tag == "label":
            self._label_depth += 1
            for_id = attrs.get("for")
            if for_id:
                self.label_for_ids.add(for_id)

        if tag == "img":
            self.images.append({"attrs": attrs, "snippet": snippet})

        if tag == "a":
            href = attrs.get("href")
            if href:
                self.links.append(href)

        if tag in self._LABELABLE_TAGS:
            input_type = attrs.get("type", "text").lower()
            if not (tag == "input" and input_type in self._SKIP_INPUT_TYPES):
                self.form_controls.append({
                    "tag": tag,
                    "attrs": attrs,
                    "snippet": snippet,
                    "in_label": self._label_depth > 0,
                })

    def handle_startendtag(self, tag, attrs_list):
        # Explicit self-closed tag, e.g. <img ... />. Route through the
        # normal start-tag handling; there is no matching end tag to pair.
        self.handle_starttag(tag, attrs_list)

    def handle_endtag(self, tag):
        if tag == "label" and self._label_depth > 0:
            self._label_depth -= 1

    @staticmethod
    def _reconstruct(tag: str, attrs_list) -> str:
        parts = [f"<{tag}"]
        for key, value in attrs_list:
            parts.append(f' {key}="{value}"' if value is not None else f" {key}")
        parts.append(">")
        return "".join(parts)


def _check_img_alt(parser: "_AccessibilityHTMLParser") -> list[dict]:
    """IMG-001: an <img> with no alt attribute at all. alt="" (decorative) is fine."""
    findings = []
    for img in parser.images:
        attrs = img["attrs"]
        if "alt" not in attrs:
            src = attrs.get("src", "")
            selector = f'img[src="{src}"]' if src else "img"
            findings.append({
                "element_selector": selector,
                "html_snippet": img["snippet"],
                "message": "Image is missing alternative text",
            })
    return findings


def _check_form_labels(parser: "_AccessibilityHTMLParser") -> list[dict]:
    """FORM-001: a form control with no label - wrapping, for=, aria-label(ledby)."""
    findings = []
    for ctrl in parser.form_controls:
        attrs = ctrl["attrs"]
        control_id = attrs.get("id")
        has_label = (
            ctrl["in_label"]
            or bool((attrs.get("aria-label") or "").strip())
            or bool((attrs.get("aria-labelledby") or "").strip())
            or (control_id is not None and control_id in parser.label_for_ids)
        )
        if not has_label:
            if control_id:
                selector = f"#{control_id}"
            elif attrs.get("name"):
                selector = f'{ctrl["tag"]}[name="{attrs["name"]}"]'
            else:
                selector = ctrl["tag"]
            findings.append({
                "element_selector": selector,
                "html_snippet": ctrl["snippet"],
                "message": "Form control does not have an accessible label",
            })
    return findings


# rule_code -> check function. A rule only produces findings if BOTH a
# check is registered here AND an enabled row for that rule_code exists
# in web_accessibility_rules (see _ensure_default_rules).
RULE_CHECKS = {
    "IMG-001": _check_img_alt,
    "FORM-001": _check_form_labels,
}


class ScanService:
    """Read/write access for scans, the async scan runner, and the joined issues-per-scan view."""

    # ---------------------------------------------------------------- create

    def _get_website(
        self, db: Session, website_id: int
    ) -> Optional[WebAccessibilityWebsiteModel]:
        return (
            db.query(WebAccessibilityWebsiteModel)
            .filter(WebAccessibilityWebsiteModel.id == website_id)
            .first()
        )

    def _get_or_create_page(
        self, db: Session, website_id: int, url: str
    ) -> WebAccessibilityPagesModel:
        """
        Find-or-create the persistent Page a scan of this (website_id, url)
        belongs to (Website 1:N Page 1:N Scan - see
        web_accessibility_pages_model.py). Mirrors _ensure_default_rules()'s
        get-or-create pattern below - there's no PageService write path yet,
        just this implicit creation the first time a URL is scanned.
        """
        url_hash = hash_page_url(url)
        page = (
            db.query(WebAccessibilityPagesModel)
            .filter(
                WebAccessibilityPagesModel.website_id == website_id,
                WebAccessibilityPagesModel.url_hash == url_hash,
            )
            .first()
        )
        if page is None:
            page = WebAccessibilityPagesModel(website_id=website_id, url=url, url_hash=url_hash)
            db.add(page)
            db.flush()  # populate page.id before the caller uses it
        return page

    def create_scan(
        self, db: Session, website_id: int, url: str, crawl_id: Optional[int] = None
    ) -> Optional[WebAccessibilityScansModel]:
        """
        Queue a new scan and persist it via WebAccessibilityScansModel.
        Returns None if the website doesn't exist; raises ValueError if
        url is missing. Does NOT run the scan itself - the router hands
        scan.id to run_scan() as a background task after this returns.

        crawl_id is set only by crawl_website() below, tagging every page
        it queues as belonging to that one crawl run - a manually-queued
        single scan leaves it None (the column default).
        """
        website = self._get_website(db, website_id)
        if not website:
            return None

        if not url or not url.strip():
            raise ValueError("url is required")
        url = url.strip()

        website_host = urlsplit(website.base_url or "").hostname
        if not website_host:
            raise ValueError("Registered website has no valid base_url host to scan against")

        scan_host = urlsplit(url).hostname
        if not scan_host or not same_domain_or_subdomain(scan_host, website_host):
            raise ValueError(
                f"url host '{scan_host}' does not match the registered website's "
                f"host '{website_host}' - a scan can only target the site it was "
                f"registered against"
            )

        page = self._get_or_create_page(db, website_id, url)

        scan = WebAccessibilityScansModel(
            website_id=website_id,
            page_id=page.id,
            crawl_id=crawl_id,
            url=url,
            status="QUEUED",
        )
        db.add(scan)
        db.commit()
        db.refresh(scan)
        logger.info(
            "Queued scan id=%s website_id=%s page_id=%s url=%s",
            scan.id, website_id, page.id, scan.url,
        )
        return scan

    def crawl_website(
        self, db: Session, website_id: int, max_pages: Optional[int] = None
    ) -> Optional[dict]:
        """
        Discover this website's pages, then queue a scan for each via the
        normal create_scan() path - every discovered page gets exactly the
        same SSRF validation, Page get-or-create, and issue dedup as a
        manually-scanned page, no separate scanning code path. Two
        discovery methods, tried in order:

            1. sitemap.xml (_discover_pages_via_sitemap) - the
               conventional /sitemap.xml, if the site has a flat one (a
               <sitemapindex> pointing at other sitemap files isn't
               handled yet - falls through to method 2). This is tried
               FIRST and preferred when available: it's the site's own
               declared, authoritative page list, immune to anything
               rendered client-side (a JS-driven nav menu that never puts
               its links in the server's raw HTML would silently defeat
               method 2, but not this one).
            2. Single-level link-scraping (_discover_pages_via_links) -
               fetch base_url itself, extract same-site <a href> links
               found directly on that ONE page (not links found on THOSE
               pages in turn - no recursion/BFS). Used only when there's
               no usable sitemap.

        Returns None if the website doesn't exist. Raises ValueError if
        the website has no valid base_url host, or if method 2 has to run
        and fetching base_url itself fails (url_guard rejection or a
        network error) - discovery happens synchronously here (not
        backgrounded like run_scan) because it has to finish before any
        scans can be queued, so a failure here means nothing was queued
        and the caller should see that immediately. A sitemap fetch
        failing/missing is NOT an error - it's the normal signal to fall
        back to method 2, since plenty of sites simply don't have one.

        max_pages caps how many pages (including the seed, when method 2
        is used) this call queues - None defaults to
        DEFAULT_CRAWL_MAX_PAGES, and the request is clamped to
        HARD_MAX_CRAWL_PAGES regardless (ScanCreateRequest's schema
        already rejects >100 with a 422; this clamp is a defense-in-depth
        backstop for any other caller).

        Writes one WebAccessibilityCrawlsModel row up front (this IS a
        persistent "crawl run" now, unlike the original single-level-only
        version of this method), then tags every scan it queues with that
        row's id via create_scan(..., crawl_id=crawl.id) - see the return
        value below and GET /scans/crawl-{id} in web_accessibility_router.py.
        Re-running this later creates a NEW crawl (and re-scans whatever
        pages are currently discoverable, picking up any new/changed
        links or sitemap entries) rather than reusing an old one - crawls
        aren't updated in place.

        Returns a dict: {"crawl": WebAccessibilityCrawlsModel,
        "pages_discovered": int, "scans": [WebAccessibilityScansModel, ...],
        "discovery_source": "sitemap" | "links"}, or None if the website
        doesn't exist.
        """
        website = self._get_website(db, website_id)
        if not website:
            return None

        website_host = urlsplit(website.base_url or "").hostname
        if not website_host:
            raise ValueError("Registered website has no valid base_url host to crawl")

        if max_pages is None:
            max_pages = DEFAULT_CRAWL_MAX_PAGES
        max_pages = max(1, min(max_pages, HARD_MAX_CRAWL_PAGES))

        discovery_source = "sitemap"
        discovered_urls = self._discover_pages_via_sitemap(website.base_url, website_host, max_pages)
        if discovered_urls is None:
            discovery_source = "links"
            discovered_urls = self._discover_pages_via_links(website.base_url, website_host, max_pages)

        crawl = WebAccessibilityCrawlsModel(
            website_id=website_id,
            discovery_source=discovery_source,
            max_pages=max_pages,
            pages_discovered=len(discovered_urls),
        )
        db.add(crawl)
        db.commit()
        db.refresh(crawl)

        scans = []
        for url in discovered_urls:
            scan = self.create_scan(db, website_id, url, crawl_id=crawl.id)
            if scan:
                scans.append(scan)

        logger.info(
            "Crawled website_id=%s crawl_id=%s source=%s discovered=%s queued=%s",
            website_id, crawl.id, discovery_source, len(discovered_urls), len(scans),
        )
        return {
            "crawl": crawl,
            "pages_discovered": len(discovered_urls),
            "scans": scans,
            "discovery_source": discovery_source,
        }

    def _discover_pages_via_sitemap(
        self, base_url: str, website_host: str, max_pages: int
    ) -> Optional[list[str]]:
        """
        Try GET {scheme+host of base_url}/sitemap.xml - the conventional
        location most sites declare via robots.txt's "Sitemap:" directive.
        Returns the same-site <loc> URLs it lists (capped at max_pages),
        or None if there's no usable FLAT sitemap here: missing/404, the
        fetch was blocked/failed, the body isn't valid XML, or the root is
        a <sitemapindex> (a sitemap made of OTHER sitemap files rather
        than pages directly - not handled by this version; a real gap for
        larger sites that shard their sitemap, but out of scope for now -
        falls back to link-scraping like any other "no sitemap" case).

        None means "fall back to link-scraping", never an error - most
        sites with a sitemap have exactly this simple flat shape, but
        plenty of sites have no sitemap at all, which is entirely normal
        and not worth failing the whole crawl over.
        """
        sitemap_url = urljoin(base_url, "/sitemap.xml")
        try:
            response = safe_fetch(
                sitemap_url,
                allowed_website_host=website_host,
                timeout=FETCH_TIMEOUT_SECONDS,
                user_agent=USER_AGENT,
            )
        except (UrlGuardError, requests.RequestException):
            return None
        if response.status_code != 200:
            return None

        try:
            root = ET.fromstring(response.content)
        except ET.ParseError:
            return None

        root_tag = root.tag.rsplit("}", 1)[-1]  # strip any {xmlns} prefix
        if root_tag != "urlset":
            return None  # <sitemapindex>, or anything unrecognized

        discovered_urls = []
        seen = set()
        for elem in root.iter():
            if elem.tag.rsplit("}", 1)[-1] != "loc":
                continue
            loc = (elem.text or "").strip()
            if not loc:
                continue
            loc, _frag = urldefrag(loc)
            if loc in seen:
                continue
            parts = urlsplit(loc)
            if parts.scheme not in ("http", "https"):
                continue
            if not parts.hostname or not same_domain_or_subdomain(parts.hostname, website_host):
                continue
            seen.add(loc)
            discovered_urls.append(loc)
            if len(discovered_urls) >= max_pages:
                break

        return discovered_urls or None  # an empty/all-filtered sitemap also falls back

    def _discover_pages_via_links(
        self, base_url: str, website_host: str, max_pages: int
    ) -> list[str]:
        """
        Fallback discovery when no usable sitemap exists: fetch base_url
        itself and extract same-site <a href> links found directly on
        that ONE page (single level - see crawl_website()'s docstring for
        why, and its limits: a page only reachable via a link on some
        OTHER page, or a link injected by client-side JavaScript rather
        than present in the server's raw HTML response, won't be found).

        Unlike the sitemap attempt, a failure here IS fatal - raises
        ValueError if base_url can't be fetched (url_guard rejection or a
        network error), since this is the last resort; nothing else is
        left to try.
        """
        try:
            response = safe_fetch(
                base_url,
                allowed_website_host=website_host,
                timeout=FETCH_TIMEOUT_SECONDS,
                user_agent=USER_AGENT,
            )
        except UrlGuardError as exc:
            raise ValueError(f"Could not crawl: {exc}") from exc
        except requests.RequestException as exc:
            raise ValueError(f"Could not fetch the site to crawl: {exc}") from exc

        parser = _AccessibilityHTMLParser()
        parser.feed(response.text)

        seed_url, _frag = urldefrag(response.url)
        discovered_urls = [seed_url]
        seen = {seed_url}

        for href in parser.links:
            absolute, _frag = urldefrag(urljoin(response.url, href))
            if absolute in seen:
                continue
            parts = urlsplit(absolute)
            if parts.scheme not in ("http", "https"):
                continue
            if not parts.hostname or not same_domain_or_subdomain(parts.hostname, website_host):
                continue
            seen.add(absolute)
            discovered_urls.append(absolute)
            if len(discovered_urls) >= max_pages:
                break

        return discovered_urls

    # ------------------------------------------------------------- execute

    def run_scan(self, scan_id: int) -> None:
        """
        Background-task entry point (see web_accessibility_router.py's
        create_scan endpoint: background_tasks.add_task(scan_service.run_scan,
        scan.id)). Fetches the scan's URL, evaluates it, and writes both
        the resulting issues and the scan's own status/rollup fields.

        Runs in its own DB session - not the request-scoped one, since
        this executes after the HTTP response has already been returned.
        """
        db = SessionLocal()
        website = None
        previous_accessibility_status = None
        try:
            scan = self._load_scan(db, scan_id)
            if not scan:
                logger.error("run_scan: scan id=%s not found", scan_id)
                return

            website = self._get_website(db, scan.website_id)
            if website is not None:
                previous_accessibility_status = website.accessibility_status

            scan.status = "RUNNING"
            scan.started_at = self._now()
            if website is not None:
                website.accessibility_status = "SCANNING"
            db.commit()

            website_host = urlsplit((website.base_url if website else "") or "").hostname

            try:
                if not website_host:
                    raise UrlGuardError(
                        f"Registered website id={scan.website_id} has no valid "
                        f"base_url host to validate this scan's url against"
                    )
                response = safe_fetch(
                    scan.url,
                    allowed_website_host=website_host,
                    timeout=FETCH_TIMEOUT_SECONDS,
                    user_agent=USER_AGENT,
                )
            except UrlGuardError as exc:
                logger.warning("run_scan: blocked scan id=%s url=%s: %s", scan_id, scan.url, exc)
                scan.status = "BLOCKED"
                scan.completed_at = self._now()
                if website is not None:
                    website.accessibility_status = previous_accessibility_status
                db.commit()
                return
            except requests.RequestException as exc:
                logger.warning("run_scan: fetch failed scan id=%s url=%s: %s", scan_id, scan.url, exc)
                scan.status = "FAILED"
                scan.completed_at = self._now()
                if website is not None:
                    website.accessibility_status = previous_accessibility_status
                db.commit()
                return

            scan.http_status = response.status_code
            title = self._extract_title(response.text)
            if title:
                scan.title = title[:500]

            findings = self._evaluate(db, response.text)

            # Dedup: the same (rule, element_selector) can legitimately show
            # up twice in one page's own HTML (e.g. an unlabeled logo <img>
            # repeated in a header and a footer) - collapse those into one
            # touch of one issue row rather than double-counting within a
            # single run.
            deduped: list[tuple[WebAccessibilityRulesModel, dict]] = []
            touched_issues: dict[tuple[int, str], WebAccessibilityIssuesModel] = {}
            for rule, finding in findings:
                key = (rule.id, finding["element_selector"])
                if key in touched_issues:
                    continue
                issue = self._upsert_issue(db, scan, rule, finding)
                touched_issues[key] = issue
                deduped.append((rule, finding))

            self._resolve_stale_issues(
                db, scan, touched_issue_ids={issue.id for issue in touched_issues.values()}
            )

            scan.total_issues = len(deduped)
            scan.accessibility_score = self._compute_score(deduped)
            scan.status = "COMPLETED"
            scan.completed_at = self._now()
            if website is not None:
                website.accessibility_status = self._derive_accessibility_status(deduped)
            db.commit()
            logger.info(
                "run_scan: completed scan id=%s http_status=%s issues=%s score=%s "
                "website_accessibility_status=%s",
                scan.id, scan.http_status, scan.total_issues, scan.accessibility_score,
                website.accessibility_status if website is not None else None,
            )

        except Exception:
            db.rollback()
            logger.exception("run_scan: unhandled error for scan id=%s", scan_id)
            self._mark_failed(
                db, scan_id,
                website=website,
                previous_accessibility_status=previous_accessibility_status,
            )
        finally:
            db.close()

    @staticmethod
    def _derive_accessibility_status(
        findings: list[tuple[WebAccessibilityRulesModel, dict]]
    ) -> str:
        """
        System-derived rollup for website.accessibility_status - the only
        place this module (or anywhere else; see website_schema.WebsiteUpdate)
        decides PASS/WARNING/FAIL. Any CRITICAL or SERIOUS finding fails the
        page outright; MODERATE/MINOR-only findings warn; no findings pass.
        """
        if not findings:
            return "PASS"
        if any((rule.severity or "").upper() in _FAILING_SEVERITIES for rule, _finding in findings):
            return "FAIL"
        return "WARNING"

    def _upsert_issue(
        self,
        db: Session,
        scan: WebAccessibilityScansModel,
        rule: WebAccessibilityRulesModel,
        finding: dict,
    ) -> WebAccessibilityIssuesModel:
        """
        Find-or-create for a single (rule, element_selector) finding on this
        scan's page. Matches against ANY prior issue for the SAME page_id
        (open or resolved - a resolved one that's back is a reopen, not a
        new defect) - page_id is a real FK to web_accessibility_pages now
        (Website 1:N Page 1:N Scan 1:N Issue), so this no longer needs a
        join through the issue's originating scan to find its website/url.
        """
        existing = (
            db.query(WebAccessibilityIssuesModel)
            .filter(
                WebAccessibilityIssuesModel.page_id == scan.page_id,
                WebAccessibilityIssuesModel.rule_id == rule.id,
                WebAccessibilityIssuesModel.element_selector == finding["element_selector"],
            )
            .first()
        )

        snippet = finding["html_snippet"]
        snippet = snippet[:MAX_SNIPPET_LENGTH] if snippet else None

        if existing is None:
            issue = WebAccessibilityIssuesModel(
                scan_id=scan.id,
                page_id=scan.page_id,
                rule_id=rule.id,
                severity=rule.severity or "MODERATE",
                status="OPEN",
                element_selector=finding["element_selector"],
                html_snippet=snippet,
                message=finding["message"],
                times_seen=1,
                last_seen_scan_id=scan.id,
            )
            db.add(issue)
            db.flush()  # populate issue.id before it's used as a dedup key
            return issue

        # Reconfirmed (already OPEN/REOPENED) or reopened (was RESOLVED) -
        # either way this is the same logical defect recurring, not a new
        # one. Only flip to REOPENED on the RESOLVED -> found-again edge,
        # so a dashboard can tell "still open since it was first seen" apart
        # from "was fixed, has now regressed" - see class docstring.
        existing.times_seen = (existing.times_seen or 0) + 1
        existing.last_seen_scan_id = scan.id
        if existing.status == "RESOLVED":
            existing.status = "REOPENED"
        existing.resolved_at = None
        existing.resolved_in_scan_id = None
        # Keep the freshest snippet/message/severity - the page markup or
        # rule metadata may have shifted slightly since this was first seen.
        if snippet:
            existing.html_snippet = snippet
        if finding.get("message"):
            existing.message = finding["message"]
        existing.severity = rule.severity or existing.severity
        return existing

    def _resolve_stale_issues(
        self,
        db: Session,
        scan: WebAccessibilityScansModel,
        touched_issue_ids: set,
    ) -> None:
        """
        Any issue that was OPEN or REOPENED for this same page before this
        scan ran, but that this scan did NOT re-find (not in
        touched_issue_ids), is fixed - mark it RESOLVED rather than leaving
        it open forever.
        """
        query = (
            db.query(WebAccessibilityIssuesModel)
            .filter(
                WebAccessibilityIssuesModel.page_id == scan.page_id,
                WebAccessibilityIssuesModel.status.in_(_OPEN_ISSUE_STATUSES),
            )
        )
        if touched_issue_ids:
            query = query.filter(WebAccessibilityIssuesModel.id.notin_(touched_issue_ids))

        now = self._now()
        for issue in query.all():
            issue.status = "RESOLVED"
            issue.resolved_at = now
            issue.resolved_in_scan_id = scan.id

    def _evaluate(self, db: Session, html: str) -> list[tuple[WebAccessibilityRulesModel, dict]]:
        """Parse html and run every registered+enabled rule check against it."""
        self._ensure_default_rules(db)

        parser = _AccessibilityHTMLParser()
        try:
            parser.feed(html)
        except Exception:
            logger.exception("run_scan: HTML parse failed")
            return []

        findings: list[tuple[WebAccessibilityRulesModel, dict]] = []
        for rule_code, check_fn in RULE_CHECKS.items():
            rule = (
                db.query(WebAccessibilityRulesModel)
                .filter(
                    WebAccessibilityRulesModel.rule_code == rule_code,
                    WebAccessibilityRulesModel.enabled.is_(True),
                )
                .first()
            )
            if not rule:
                continue  # not seeded/enabled - skip rather than fail the scan
            findings.extend((rule, finding) for finding in check_fn(parser))
        return findings

    def _ensure_default_rules(self, db: Session) -> None:
        for spec in _DEFAULT_RULES:
            exists = (
                db.query(WebAccessibilityRulesModel.id)
                .filter(WebAccessibilityRulesModel.rule_code == spec["rule_code"])
                .first()
            )
            if not exists:
                db.add(WebAccessibilityRulesModel(**spec, enabled=True))
        db.commit()

    def _mark_failed(
        self,
        db: Session,
        scan_id: int,
        website: Optional[WebAccessibilityWebsiteModel] = None,
        previous_accessibility_status: Optional[str] = None,
    ) -> None:
        """
        Last-resort cleanup after an unhandled error in run_scan(): mark the
        scan FAILED and, if this run had already flipped the website to
        SCANNING, put its accessibility_status back the way it was - an
        unhandled error means no real assessment happened either.
        """
        try:
            scan = self._load_scan(db, scan_id)
            if scan:
                scan.status = "FAILED"
                scan.completed_at = self._now()
            if website is not None:
                website.accessibility_status = previous_accessibility_status
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("run_scan: failed to mark scan id=%s as FAILED", scan_id)

    @staticmethod
    def _load_scan(db: Session, scan_id: int) -> Optional[WebAccessibilityScansModel]:
        return (
            db.query(WebAccessibilityScansModel)
            .filter(WebAccessibilityScansModel.id == scan_id)
            .first()
        )

    @staticmethod
    def _now() -> datetime:
        # Naive UTC, to match the naive TIMESTAMP columns on this model
        # (func.current_timestamp() elsewhere is likewise naive).
        return datetime.now(timezone.utc).replace(tzinfo=None)

    @staticmethod
    def _extract_title(html: str) -> Optional[str]:
        match = _TITLE_RE.search(html or "")
        if not match:
            return None
        return re.sub(r"\s+", " ", match.group(1)).strip() or None

    @staticmethod
    def _compute_score(findings: list[tuple[WebAccessibilityRulesModel, dict]]) -> Decimal:
        """
        Simple heuristic, not a standardized WCAG conformance score: start
        at 100, subtract a per-issue penalty scaled by the rule's severity.
        """
        score = 100.0
        for rule, _finding in findings:
            score -= _SEVERITY_PENALTY.get((rule.severity or "").upper(), _DEFAULT_PENALTY)
        return Decimal(str(round(max(0.0, score), 2)))

    # --------------------------------------------------------------- reads

    def get_scan_by_id(self, db: Session, scan_id: int) -> Optional[WebAccessibilityScansModel]:
        """Get a single scan by ID."""
        return self._load_scan(db, scan_id)

    def get_scans_for_website(self, db: Session, website_id: int):
        """List a website's scans, most recent first. Returns None if the website doesn't exist."""
        if not self._get_website(db, website_id):
            return None

        return (
            db.query(WebAccessibilityScansModel)
            .filter(WebAccessibilityScansModel.website_id == website_id)
            .order_by(WebAccessibilityScansModel.id.desc())
            .all()
        )

    def get_crawl_by_id(self, db: Session, crawl_id: int) -> Optional[WebAccessibilityCrawlsModel]:
        """Get a single crawl run by ID."""
        return (
            db.query(WebAccessibilityCrawlsModel)
            .filter(WebAccessibilityCrawlsModel.id == crawl_id)
            .first()
        )

    def get_crawls_for_website(self, db: Session, website_id: int):
        """
        List a website's crawl runs (each one an all_pages=true request -
        see crawl_website()), most recent first. Returns None if the
        website doesn't exist. Backs GET /websites/{id}/crawls.
        """
        if not self._get_website(db, website_id):
            return None

        return (
            db.query(WebAccessibilityCrawlsModel)
            .filter(WebAccessibilityCrawlsModel.website_id == website_id)
            .order_by(WebAccessibilityCrawlsModel.id.desc())
            .all()
        )

    def get_scans_for_crawl(self, db: Session, crawl_id: int):
        """
        Every page-scan a given crawl run queued, in the order they were
        created (not most-recent-first like the history listings - this
        backs GET /scans/crawl-{id}'s page-wise breakdown, where a stable
        "discovery order" reads more naturally than newest-first).
        """
        return (
            db.query(WebAccessibilityScansModel)
            .filter(WebAccessibilityScansModel.crawl_id == crawl_id)
            .order_by(WebAccessibilityScansModel.id.asc())
            .all()
        )

    @staticmethod
    def derive_crawl_status(scans: list) -> str:
        """
        System-derived rollup for a crawl run's overall status, from its
        pages' individual scan statuses - mirrors _derive_accessibility_status()'s
        role for a single website, but summarizing progress/outcome
        instead of a pass/fail assessment. QUEUED/RUNNING dominate (the
        crawl is still in flight) over any terminal state; once every
        page has finished, all-COMPLETED reports COMPLETED, anything else
        (a mix including FAILED/BLOCKED) reports PARTIAL rather than
        silently hiding that some pages didn't complete cleanly.
        """
        statuses = {scan.status for scan in scans}
        if not statuses:
            return "COMPLETED"  # no pages were discovered/queued
        if "RUNNING" in statuses:
            return "RUNNING"
        if "QUEUED" in statuses:
            return "QUEUED"
        if statuses <= {"COMPLETED"}:
            return "COMPLETED"
        return "PARTIAL"

    def get_scan_issues(
        self,
        db: Session,
        scan_id: int,
        status: Optional[str] = None,
        severity: Optional[str] = None,
        rule_code: Optional[str] = None,
    ):
        """
        List issues this scan originally created or most recently
        reconfirmed, joined with their rule metadata. Returns None if the
        scan doesn't exist, else a list of dicts shaped for the API response
        (see web_accessibility_router.py). NOTE: fields like times_seen,
        status, and resolved_at always reflect each issue's CURRENT state,
        not a snapshot from when this particular scan ran - see the module
        docstring's "Issue lifecycle / dedup" note.
        """
        scan = self.get_scan_by_id(db, scan_id)
        if not scan:
            return None

        query = (
            db.query(WebAccessibilityIssuesModel, WebAccessibilityRulesModel)
            .join(
                WebAccessibilityRulesModel,
                WebAccessibilityIssuesModel.rule_id == WebAccessibilityRulesModel.id,
            )
            .filter(
                or_(
                    WebAccessibilityIssuesModel.scan_id == scan_id,
                    WebAccessibilityIssuesModel.last_seen_scan_id == scan_id,
                )
            )
        )

        if status:
            query = query.filter(WebAccessibilityIssuesModel.status == status)
        if severity:
            query = query.filter(WebAccessibilityIssuesModel.severity == severity)
        if rule_code:
            query = query.filter(WebAccessibilityRulesModel.rule_code == rule_code)

        rows = query.order_by(WebAccessibilityIssuesModel.id.asc()).all()
        return [self._format_issue(issue, rule) for issue, rule in rows]

    @staticmethod
    def _format_issue(
        issue: WebAccessibilityIssuesModel, rule: WebAccessibilityRulesModel
    ) -> dict:
        return {
            "id": issue.id,
            "scan_id": issue.scan_id,
            "rule_code": rule.rule_code,
            "rule_name": rule.name,
            "wcag_criterion": rule.wcag_criterion,
            "wcag_level": rule.wcag_level,
            "category": rule.category,
            "severity": issue.severity,
            "status": issue.status,
            "element_selector": issue.element_selector,
            "html_snippet": issue.html_snippet,
            "message": issue.message,
            "times_seen": issue.times_seen,
            "last_seen_scan_id": issue.last_seen_scan_id,
            "resolved_at": issue.resolved_at,
            "resolved_in_scan_id": issue.resolved_in_scan_id,
        }
