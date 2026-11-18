"""
hyperlink_agent.py
==================
HyperlinkAgent — validates every hyperlink on every slide (including links inside
grouped shapes).

Checks (supported_checks)
    PPT-LINK-001  Broken links     (structurally invalid / malformed URL)
    PPT-LINK-002  Raw URLs         (visible link text is the URL itself)
    PPT-LINK-003  "Click here"     (non-descriptive / empty link text — WCAG 2.4.4)
    PPT-LINK-004  Missing tooltip  (hyperlink with no ScreenTip)

Reads the normalized context from ppt_loader: each shape carries
    shape["hyperlinks"] = [ {"text": str, "url": str, "tooltip": str|None}, ... ]

"Broken" is judged STRUCTURALLY only — no network requests are made (a validator
must be deterministic and offline-safe). A link is broken when its URL is empty,
a bare placeholder, contains whitespace, or is an http(s)/mailto URL with no
host/address. Live reachability is out of scope.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from src.modules.accessibility_pdf.models.validation_issue import ValidationIssue
from src.modules.accessibility_ppt.engine.ppt_validator.base_agent import (
    BasePPTAccessibilityValidatorAgent,
)

# Non-descriptive link phrases (WCAG 2.4.4 "Link Purpose").
_GENERIC_LINK_TEXT = {
    "click here", "click", "here", "link", "this link", "this", "read more",
    "more", "learn more", "see more", "go", "go here", "download", "click this",
    "click to read", "read", "info", "details", "this page", "website", "url",
}
_URL_LIKE = re.compile(r"^\s*(https?://|www\.|ftp://)", re.I)
_BARE_PLACEHOLDER = {"#", "http://", "https://", "mailto:", "www.", ""}


class HyperlinkAgent(BasePPTAccessibilityValidatorAgent):
    """Validate hyperlink integrity and descriptiveness across slides."""

    agent_code = "PPT_HYPERLINK_AGENT"
    agent_name = "PPT Hyperlink Agent"
    category = "Links"
    supported_checks = {
        "PPT-LINK-001",
        "PPT-LINK-002",
        "PPT-LINK-003",
        "PPT-LINK-004",
    }

    # ---------------------------------------------------------------- dispatch
    def run_check(self, check_code: str, context: dict[str, Any]) -> ValidationIssue:
        slides = context.get("slides")
        slides = slides if isinstance(slides, list) else []
        links = list(self._iter_links(slides))

        dispatch = {
            "PPT-LINK-001": self._check_broken,
            "PPT-LINK-002": self._check_raw_urls,
            "PPT-LINK-003": self._check_generic_text,
            "PPT-LINK-004": self._check_tooltip,
        }
        handler = dispatch.get(check_code)
        if handler is None:
            return self._info(check_code, f"Check {check_code} is not implemented yet",
                              "Implement the requested hyperlink check")
        return handler(links)

    # ---------------------------------------------------------------- helpers
    def _issue(self, rule_id, severity, status, message, recommendation,
               page_no=None, auto_fixable=False, internal=False) -> ValidationIssue:
        return ValidationIssue(
            agent_name=self.agent_name, rule_id=rule_id, category=self.category,
            severity=severity, page_no=page_no, message=message,
            recommendation=recommendation, auto_fixable=auto_fixable,
            status=status, internal_check=internal,
        )

    def _pass(self, rule_id, message, recommendation) -> ValidationIssue:
        return self._issue(rule_id, "LOW", "PASS", message, recommendation)

    def _info(self, rule_id, message, recommendation) -> ValidationIssue:
        return self._issue(rule_id, "LOW", "INFO", message, recommendation,
                           internal=True)

    @staticmethod
    def _slide_no(slide: dict, order_idx: int) -> int:
        idx = slide.get("index")
        return (idx + 1) if isinstance(idx, int) else (order_idx + 1)

    def _iter_links(self, slides):
        """Yield (slide_no, link_dict) for every hyperlink, recursing groups."""
        def walk(shapes, sno):
            for sh in shapes:
                if not isinstance(sh, dict):
                    continue
                for lk in (sh.get("hyperlinks") or []):
                    if isinstance(lk, dict):
                        yield sno, lk
                kids = sh.get("shapes")
                if isinstance(kids, list):
                    yield from walk(kids, sno)

        for order_idx, slide in enumerate(slides):
            if not isinstance(slide, dict):
                continue
            sno = self._slide_no(slide, order_idx)
            shapes = slide.get("shapes")
            if isinstance(shapes, list):
                yield from walk(shapes, sno)

    # ---------------------------------------------------------- broken utils
    @staticmethod
    def _is_broken(url) -> bool:
        if not isinstance(url, str):
            return True
        u = url.strip()
        if u.lower() in _BARE_PLACEHOLDER:
            return True
        if any(ch.isspace() for ch in u):
            return True
        try:
            p = urlparse(u)
        except Exception:
            return True
        scheme = p.scheme.lower()
        if scheme in ("http", "https"):
            # Require a host, but do NOT require a dot: single-label intranet
            # hosts (http://intranet/page) are legitimate and must not be flagged.
            return not p.netloc
        if scheme == "mailto":
            return "@" not in p.path
        # tel:, ftp:, file:, internal slide actions, or scheme-less relative
        # links are not judged broken here (can't verify offline).
        return False

    @staticmethod
    def _text_is_url(text) -> bool:
        return isinstance(text, str) and bool(_URL_LIKE.match(text))

    # ------------------------------------------------------------- 001 broken
    def _check_broken(self, links) -> ValidationIssue:
        if not links:
            return self._pass("PPT-LINK-001", "No hyperlinks found.",
                              "Verify URLs when you add links.")
        bad = [(sno, lk.get("url")) for sno, lk in links if self._is_broken(lk.get("url"))]
        if bad:
            slides_hit = sorted({s for s, _ in bad})
            ex = "; ".join(f"'{(u or '')[:40]}'" for _, u in bad[:3])
            return self._issue(
                "PPT-LINK-001", "HIGH", "FAIL",
                f"{len(bad)} hyperlink(s) have a malformed/empty URL on slide(s) "
                f"{', '.join(map(str, slides_hit))} (e.g. {ex}).",
                "Fix or remove links with empty/placeholder/malformed URLs so they "
                "point at a valid destination.",
                page_no=slides_hit[0], auto_fixable=False)
        return self._pass("PPT-LINK-001",
                          f"All {len(links)} hyperlink URL(s) are well-formed.",
                          "Keep link URLs valid.")

    # ------------------------------------------------------------- 002 raw url
    def _check_raw_urls(self, links) -> ValidationIssue:
        if not links:
            return self._pass("PPT-LINK-002", "No hyperlinks found.",
                              "Use descriptive link text, not raw URLs.")
        raw = []
        for sno, lk in links:
            text = (lk.get("text") or "").strip()
            url = (lk.get("url") or "").strip()
            if self._text_is_url(text) or (text and text == url):
                raw.append((sno, text))
        if raw:
            slides_hit = sorted({s for s, _ in raw})
            return self._issue(
                "PPT-LINK-002", "LOW", "WARNING",
                f"{len(raw)} link(s) display a raw URL as their text on slide(s) "
                f"{', '.join(map(str, slides_hit))}.",
                "Replace the visible URL with descriptive text (e.g. 'Annual "
                "report 2025'); screen readers read a raw URL out character by "
                "character.",
                page_no=slides_hit[0], auto_fixable=False)
        return self._pass("PPT-LINK-002",
                          "No links display raw URLs as their text.",
                          "Keep link text human-readable.")

    # --------------------------------------------------------- 003 generic text
    def _check_generic_text(self, links) -> ValidationIssue:
        if not links:
            return self._pass("PPT-LINK-003", "No hyperlinks found.",
                              "Use descriptive link text.")
        generic, empty = [], []
        for sno, lk in links:
            text = (lk.get("text") or "").strip()
            if not text:
                empty.append(sno)
            elif text.casefold() in _GENERIC_LINK_TEXT:
                generic.append((sno, text))
        hits = generic + [(s, "") for s in empty]
        if hits:
            slides_hit = sorted({s for s, _ in hits})
            detail = []
            if generic:
                detail.append(f"{len(generic)} non-descriptive "
                              f"(e.g. '{generic[0][1]}')")
            if empty:
                detail.append(f"{len(empty)} with no visible text")
            return self._issue(
                "PPT-LINK-003", "MEDIUM", "FAIL",
                f"{len(hits)} link(s) lack meaningful text on slide(s) "
                f"{', '.join(map(str, slides_hit))}: {', '.join(detail)}.",
                "Write link text that describes the destination out of context "
                "(WCAG 2.4.4) instead of 'click here'/'read more'.",
                page_no=slides_hit[0], auto_fixable=False)
        return self._pass("PPT-LINK-003",
                          "All links have descriptive text.",
                          "Keep link text meaningful on its own.")

    # ------------------------------------------------------------- 004 tooltip
    def _check_tooltip(self, links) -> ValidationIssue:
        if not links:
            return self._pass("PPT-LINK-004", "No hyperlinks found.",
                              "Add a ScreenTip to links where it aids clarity.")
        missing = [sno for sno, lk in links
                   if not (isinstance(lk.get("tooltip"), str) and lk["tooltip"].strip())]
        if missing:
            slides_hit = sorted(set(missing))
            return self._issue(
                "PPT-LINK-004", "LOW", "WARNING",
                f"{len(missing)} hyperlink(s) have no ScreenTip/tooltip on slide(s) "
                f"{', '.join(map(str, slides_hit))}.",
                "Add a ScreenTip (Insert > Link > ScreenTip) to give extra context "
                "about where the link goes, especially when text is short.",
                page_no=slides_hit[0], auto_fixable=False)
        return self._pass("PPT-LINK-004",
                          f"All {len(links)} hyperlink(s) have a ScreenTip.",
                          "Keep ScreenTips on links for added context.")
