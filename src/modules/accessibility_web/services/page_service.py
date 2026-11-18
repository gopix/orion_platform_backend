"""
page_service.py - Read-only access for the web_accessibility_pages
resource.

Pages are created implicitly by scan_service.create_scan()'s
get-or-create (_get_or_create_page) the first time a URL is scanned - by
a manual POST .../scan, or by that same endpoint's all_pages=true mode
(scan_service.crawl_website) discovering it. There's no write path here,
deliberately: a page coming into existence is a side effect of scanning
it, not something a client creates directly. This service backs GET
/pages/{page_id}/scans - a single page's full scan history. (There used
to also be a GET /websites/{id}/pages page-wise status listing here;
removed as unneeded - GET /websites/{id}/scan already gives the full
scan history across a website, and GET /pages/{id}/scans covers one page
at a time.) See scan_service.py's module docstring for the full
Website 1:N Page 1:N Scan 1:N Issue picture.
"""

from typing import Optional

from sqlalchemy.orm import Session

from src.core.logger import get_logger
from src.modules.accessibility_web.models.web_accessibility_pages_model import (
    WebAccessibilityPagesModel,
)
from src.modules.accessibility_web.models.web_accessibility_scans_model import (
    WebAccessibilityScansModel,
)

logger = get_logger(__name__)


class PageService:

    def get_page_by_id(
        self, db: Session, page_id: int
    ) -> Optional[WebAccessibilityPagesModel]:
        """Get a single page by ID."""
        return (
            db.query(WebAccessibilityPagesModel)
            .filter(WebAccessibilityPagesModel.id == page_id)
            .first()
        )

    def get_scans_for_page(self, db: Session, page_id: int):
        """
        List a page's scan history, most recent first. Returns None if the
        page doesn't exist.
        """
        page = self.get_page_by_id(db, page_id)
        if not page:
            return None

        return (
            db.query(WebAccessibilityScansModel)
            .filter(WebAccessibilityScansModel.page_id == page_id)
            .order_by(WebAccessibilityScansModel.id.desc())
            .all()
        )
