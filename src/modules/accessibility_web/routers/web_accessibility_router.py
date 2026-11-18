"""
web_accessibility_router.py - FastAPI router for the Orion Web Accessibility
module.

Three resource slices are wired end-to-end so far:

    Websites:
        web_accessibility_router.py -> website_service.py
            -> web_accessibility_websites_model.py -> DB

    Scans (+ their issues, embedded inline - no separate issues
    endpoint) - also backs GET /pages/{page_id}/scans via page_service.py
    (see its module docstring for why there's no page write endpoint):
        web_accessibility_router.py -> scan_service.py
            -> web_accessibility_pages_model.py -> DB (get-or-create per url)
            -> web_accessibility_crawls_model.py -> DB (all_pages=true requests only)
            -> web_accessibility_scans_model.py -> DB
            -> web_accessibility_issues_model.py / web_accessibility_rules_model.py -> DB
              (joined, embedded into GET /scans/{scan_id}'s response)

    The full chain is Website 1:N Page 1:N Scan 1:N Issue - see
    scan_service.py's module docstring for the rationale (a Page is a
    persistent entity a URL represents; a Scan is one run against it).

A website must be registered before it can be scanned. POST .../scan writes
a QUEUED scan row via scan_service.create_scan(), then hands the new scan's
id to scan_service.run_scan() as a FastAPI BackgroundTask - it runs after
the 202 response is sent, fetches the URL, evaluates it against the rule
checks in scan_service.RULE_CHECKS, and writes any findings as
WebAccessibilityIssuesModel rows before rolling the scan to COMPLETED/FAILED.
The same POST .../scan endpoint also handles the bulk case: payload.
all_pages=true discovers every page on the site (sitemap-first, falling
back to single-level homepage link-scraping if there's no usable sitemap -
see scan_service.crawl_website()) and queues a scan for each, the same way,
just done in bulk instead of the caller already knowing and posting every
page URL individually. This used to be a separate POST .../crawl endpoint;
folded into .../scan instead so there's one endpoint and one request shape
to queue scans, rather than two endpoints whose only real difference was
"one url vs many" - see ScanCreateRequest's docstring for the two request
shapes. A bulk request also writes one WebAccessibilityCrawlsModel row
("crawl run") and tags every scan it queues with that row's id
(crawl_id) - see "Scan vs crawl addressing" below.
This is a lightweight static-HTML fetch + parse (stdlib html.parser), not a
headless-browser render - no such dependency is installed in this project.
The fetch itself goes through acquisition/url_guard.safe_fetch(), which
rejects a scan url whose host doesn't match the registered website (see
scan_service.create_scan - returns 400 immediately, no background task is
queued) and blocks the fetch (scan.status=BLOCKED) if the url or any
redirect hop it follows resolves to a private/reserved address that isn't
on settings.scan_private_ip_allowlist.
remediation_service.py, validation_service.py and report_service.py are
still empty stubs.

All endpoints below - website and scan/issue alike - return the same
{response_code, message, data, errors} envelope via build_response().
Scan/issue endpoints originally returned bare JSON bodies per an earlier
version of this slice's API contract; standardized on the envelope after
a review flagged the inconsistency, before any frontend/dashboard client
existed to depend on the old shape. POST .../scan's queued-scan summary
and the {items, total} history listings now live under "data".

web_accessibility_issues rows are persistent defects, deduplicated across
scans of the same page, not one-row-per-scan snapshots - see
scan_service.py's module docstring ("Issue lifecycle / dedup") for the
matching key and what GET /scans/{scan_id}'s embedded issues does and
doesn't show. There used to be a separate GET /scans/{scan_id}/issues
endpoint; folded into GET /scans/{scan_id} itself instead (one fewer
round-trip to see a scan's findings - issues live under "issues" in that
response now) exactly the way POST .../crawl was folded into POST .../scan.

Scan vs crawl addressing: a manually-queued single-page scan (all_pages
omitted/false) is fetched via GET /scans/{scan_id} - a plain integer,
that page's own result+issues. An all_pages=true request's result is
fetched a different way, scoped under its website: GET
/websites/{website_id}/crawls/{crawl_id} returns every discovered page's
result, issues included, as ONE response ("pages": [...], page-wise) -
this is what POST .../scan's all_pages=true response's "crawl_id" field
is for polling. GET /scans/{scan_id} never returns a crawl, even for one
of the individual page-scans a crawl queued (its own scan_id still works
there, same as any scan) - one id shape, one meaning, no prefix needed
to disambiguate. See get_scan() and get_website_crawl() below for the
exact response shapes.

Endpoints (mounted under /api/v1/web-accessibility, see api_router.py):

    POST   /websites                       Register a website for scanning
    GET    /websites                       List registered websites
    GET    /websites/{website_id}          Get a single website
    PUT    /websites/{website_id}          Update a website
    DELETE /websites/{website_id}          Remove a website

    POST   /websites/{website_id}/scan     Queue a scan - one page (url), or every
                                            page on the site (all_pages=true,
                                            sitemap-first, max_pages capped)
    GET    /websites/{website_id}/scan/history   Get a website's scan history
    GET    /websites/{website_id}/crawls         List a website's crawl runs
    GET    /websites/{website_id}/crawls/{crawl_id}  Get one crawl's page-wise
                                                  result, issues embedded
    GET    /pages/{page_id}/scans          Get a page's scan history
    GET    /scans/{scan_id}                Get one page's own scan status/
                                            results, issues embedded
                                            (filters: ?status=&severity=&rule_code=)
"""

from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.core.logger import get_logger
from src.core.response import build_response
from src.modules.accessibility_web.schemas.scan_schema import ScanCreateRequest
from src.modules.accessibility_web.schemas.website_schema import (
    WebsiteCreate,
    WebsiteUpdate,
)
from src.modules.accessibility_web.services.page_service import PageService
from src.modules.accessibility_web.services.scan_service import ScanService
from src.modules.accessibility_web.services.website_Service import WebsiteService

router = APIRouter()
logger = get_logger(__name__)

website_service = WebsiteService()
page_service = PageService()
scan_service = ScanService()


# ==================== Website CRUD Endpoints ====================

@router.post("/websites", status_code=status.HTTP_201_CREATED)
def create_website(payload: WebsiteCreate, db: Session = Depends(get_db)):
    """Register a new website for accessibility scanning."""
    try:
        website = website_service.create_website(
            db=db,
            base_url=payload.base_url,
            name=payload.name,
            description=payload.description,
            environment=payload.environment,
            crawl_enabled=payload.crawl_enabled,
            crawl_frequency=payload.crawl_frequency,
            authentication_required=payload.authentication_required,
            authentication_type=payload.authentication_type,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    return build_response(
        response_code=status.HTTP_201_CREATED,
        message="Website registered successfully",
        data=website.to_dict(),
    )


@router.get("/websites")
def get_all_websites(
    db: Session = Depends(get_db),
    environment: Optional[str] = Query(None, description="Filter by environment, e.g. PRODUCTION"),
    crawl_enabled: Optional[bool] = Query(None, description="Filter by crawl_enabled"),
):
    """List registered websites, optionally filtered by environment and/or crawl_enabled."""
    websites = website_service.get_all_websites(
        db=db, environment=environment, crawl_enabled=crawl_enabled
    )
    return build_response(
        response_code=status.HTTP_200_OK,
        message="Websites retrieved successfully",
        data=[w.to_dict() for w in websites],
    )


@router.get("/websites/{website_id}")
def get_website(website_id: int, db: Session = Depends(get_db)):
    """Get a single website by ID."""
    website = website_service.get_website_by_id(db=db, website_id=website_id)
    if not website:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Website not found")

    return build_response(
        response_code=status.HTTP_200_OK,
        message="Website retrieved successfully",
        data=website.to_dict(),
    )


@router.put("/websites/{website_id}")
def update_website(website_id: int, payload: WebsiteUpdate, db: Session = Depends(get_db)):
    """Update a website. Only fields present in the payload are changed."""
    try:
        website = website_service.update_website(
            db=db,
            website_id=website_id,
            **payload.model_dump(exclude_unset=True),
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    if not website:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Website not found")

    return build_response(
        response_code=status.HTTP_200_OK,
        message="Website updated successfully",
        data=website.to_dict(),
    )


@router.delete("/websites/{website_id}")
def delete_website(website_id: int, db: Session = Depends(get_db)):
    """Delete a website."""
    success = website_service.delete_website(db=db, website_id=website_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Website not found")

    return build_response(
        response_code=status.HTTP_200_OK,
        message="Website deleted successfully",
        data={"id": website_id},
    )


# ==================== Scan & Issues Endpoints ====================

@router.post("/websites/{website_id}/scan", status_code=status.HTTP_202_ACCEPTED)
def create_scan(
    website_id: int,
    payload: ScanCreateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Queue scan(s) for a website and kick off the actual fetch(es) in the
    background - returns 202 immediately either way (see
    ScanCreateRequest's docstring for the two request shapes):

      - payload.all_pages is false/omitted (default): queue exactly the
        one page at payload.url. Poll GET /scans/{scan_id} for progress
        (QUEUED -> RUNNING -> COMPLETED/FAILED/BLOCKED - BLOCKED means
        url_guard rejected the url or a redirect target, see
        acquisition/url_guard.py).
      - payload.all_pages is true: discover every page on the site
        (sitemap-first, falling back to single-level homepage
        link-scraping - see scan_service.crawl_website()) and queue a
        scan for each, exactly like the single-page path just done in
        bulk - payload.url is ignored in this mode. Poll the returned
        crawl_id via GET /websites/{website_id}/crawls/{crawl_id} for
        the page-wise result (issues included) once everything
        completes - see that endpoint's docstring for the response shape.
    """
    if payload.all_pages:
        try:
            result = scan_service.crawl_website(db=db, website_id=website_id, max_pages=payload.max_pages)
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

        if result is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Website not found")

        scans = result["scans"]
        for scan in scans:
            background_tasks.add_task(scan_service.run_scan, scan.id)

        return build_response(
            response_code=status.HTTP_202_ACCEPTED,
            message="Crawl queued successfully",
            data={
                "crawl_id": result["crawl"].id,
                "website_id": website_id,
                "discovery_source": result["discovery_source"],
                "pages_discovered": result["pages_discovered"],
                "scans_queued": [
                    {"scan_id": s.id, "url": s.url, "status": s.status} for s in scans
                ],
            },
        )

    try:
        scan = scan_service.create_scan(db=db, website_id=website_id, url=payload.url)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    if not scan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Website not found")

    background_tasks.add_task(scan_service.run_scan, scan.id)

    return build_response(
        response_code=status.HTTP_202_ACCEPTED,
        message="Scan queued successfully",
        data={
            "scan_id": scan.id,
            "website_id": scan.website_id,
            "url": scan.url,
            "status": scan.status,
        },
    )


@router.get("/scans/{scan_id}")
def get_scan(
    scan_id: int,
    db: Session = Depends(get_db),
    status_filter: Optional[str] = Query(
        None, alias="status", description="Filter embedded issues by status, e.g. OPEN"
    ),
    severity: Optional[str] = Query(None, description="Filter embedded issues by severity, e.g. CRITICAL"),
    rule_code: Optional[str] = Query(None, description="Filter embedded issues by rule code, e.g. IMG-001"),
):
    """
    Get one page's own scan - status/results, issues embedded inline
    (there's no separate .../issues endpoint - see the module docstring).
    Issues are persistent defects, not per-scan snapshots - re-scanning
    the same page doesn't create duplicate rows for a still-open problem
    (see scan_service.py's module docstring, "Issue lifecycle / dedup");
    each item's status/times_seen/resolved_at reflect its CURRENT state,
    not a snapshot frozen at this particular scan's run time.
    status/severity/rule_code filter the embedded issues the same way the
    old .../issues endpoint did.

    For a scan that was queued as part of an all_pages=true crawl, this
    still returns just that ONE page's result - to see every page a
    crawl touched at once, use GET /websites/{website_id}/crawls/{crawl_id}
    instead (this scan's "crawl_id" field says which crawl, if any, it
    belongs to).
    """
    scan = scan_service.get_scan_by_id(db=db, scan_id=scan_id)
    if not scan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scan not found")

    data = scan.to_dict()
    data["issues"] = scan_service.get_scan_issues(
        db=db, scan_id=scan.id, status=status_filter, severity=severity, rule_code=rule_code,
    ) or []

    return build_response(
        response_code=status.HTTP_200_OK,
        message="Scan retrieved successfully",
        data=data,
    )


@router.get("/websites/{website_id}/scan/history")
def get_website_scan_history(website_id: int, db: Session = Depends(get_db)):
    """List a website's scan history (every page), most recent first."""
    scans = scan_service.get_scans_for_website(db=db, website_id=website_id)
    if scans is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Website not found")

    items = [_scan_history_item(s) for s in scans]
    return build_response(
        response_code=status.HTTP_200_OK,
        message="Website scan history retrieved successfully",
        data={"items": items, "total": len(items)},
    )


@router.get("/websites/{website_id}/crawls")
def get_website_crawls(website_id: int, db: Session = Depends(get_db)):
    """
    List a website's crawl runs (each one an all_pages=true request - see
    scan_service.crawl_website()), most recent first. A trimmed summary
    per crawl, not the page-wise detail - see GET
    /websites/{website_id}/crawls/{crawl_id} for that.
    """
    crawls = scan_service.get_crawls_for_website(db=db, website_id=website_id)
    if crawls is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Website not found")

    items = []
    for crawl in crawls:
        scans = scan_service.get_scans_for_crawl(db=db, crawl_id=crawl.id)
        items.append({
            "crawl_id": crawl.id,
            "status": scan_service.derive_crawl_status(scans),
            "discovery_source": crawl.discovery_source,
            "pages_discovered": crawl.pages_discovered,
            "created_at": crawl.created_at,
        })

    return build_response(
        response_code=status.HTTP_200_OK,
        message="Website crawl history retrieved successfully",
        data={"items": items, "total": len(items)},
    )


@router.get("/websites/{website_id}/crawls/{crawl_id}")
def get_website_crawl(
    website_id: int,
    crawl_id: int,
    db: Session = Depends(get_db),
    status_filter: Optional[str] = Query(
        None, alias="status", description="Filter embedded issues by status, e.g. OPEN"
    ),
    severity: Optional[str] = Query(None, description="Filter embedded issues by severity, e.g. CRITICAL"),
    rule_code: Optional[str] = Query(None, description="Filter embedded issues by rule code, e.g. IMG-001"),
):
    """
    Get one crawl run's page-wise detail, scoped to this website - every
    page that crawl discovered, each with its own embedded "issues" list
    (status/severity/rule_code filter those the same way GET
    /scans/{scan_id} does). 404s if crawl_id doesn't exist, OR if it
    exists but belongs to a DIFFERENT website - a crawl is never
    reachable through the wrong website's path.

    This is the ONLY way to fetch a crawl's detail - GET /scans/{scan_id}
    only ever returns a single page's own scan, never a crawl (see its
    docstring). Poll this endpoint with the crawl_id POST
    /websites/{website_id}/scan (all_pages=true) returned.
    """
    crawl = scan_service.get_crawl_by_id(db=db, crawl_id=crawl_id)
    if not crawl or crawl.website_id != website_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Crawl not found")

    scans = scan_service.get_scans_for_crawl(db=db, crawl_id=crawl_id)
    pages = []
    for scan in scans:
        page_data = scan.to_dict()
        page_data["issues"] = scan_service.get_scan_issues(
            db=db, scan_id=scan.id, status=status_filter, severity=severity, rule_code=rule_code,
        ) or []
        pages.append(page_data)

    return build_response(
        response_code=status.HTTP_200_OK,
        message="Crawl retrieved successfully",
        data={
            "crawl_id": crawl.id,
            "website_id": crawl.website_id,
            "status": scan_service.derive_crawl_status(scans),
            "discovery_source": crawl.discovery_source,
            "pages_discovered": crawl.pages_discovered,
            "pages": pages,
        },
    )


@router.get("/pages/{page_id}/scans")
def get_page_scan_history(page_id: int, db: Session = Depends(get_db)):
    """List one page's scan history, most recent first."""
    scans = page_service.get_scans_for_page(db=db, page_id=page_id)
    if scans is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found")

    items = [_scan_history_item(s) for s in scans]
    return build_response(
        response_code=status.HTTP_200_OK,
        message="Page scan history retrieved successfully",
        data={"items": items, "total": len(items)},
    )


def _scan_history_item(scan) -> dict:
    """Shared trimmed shape for both scan-history listings above."""
    return {
        "id": scan.id,
        "page_id": scan.page_id,
        "crawl_id": scan.crawl_id,
        "url": scan.url,
        "status": scan.status,
        "total_issues": scan.total_issues,
        "accessibility_score": float(scan.accessibility_score) if scan.accessibility_score is not None else None,
        "completed_at": scan.completed_at,
    }
