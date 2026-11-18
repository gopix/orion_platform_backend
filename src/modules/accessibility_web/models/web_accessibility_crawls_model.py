"""
web_accessibility_crawls_model.py - the parent record for one
POST /websites/{id}/scan (all_pages=true) request, a "crawl run".

Exists purely so the several per-page Scan rows one such request creates
can be looked up together, page-wise, as a SINGLE result via
GET /scans/crawl-{id} (see web_accessibility_router.py's get_scan()) -
instead of the caller having to poll every individual scan_id itself. A
crawl has no findings of its own: accessibility_score/status stay owned
by the underlying Scan/Issue rows exactly as for a manually-queued scan;
this table is a grouping/summary record only, written once by
scan_service.crawl_website() and never updated afterward.

A manually-queued single-page scan (all_pages omitted/false) has no
crawl - web_accessibility_scans.crawl_id stays NULL for those rows, see
web_accessibility_scans_model.py.
"""

from sqlalchemy import (
    BigInteger,
    Column,
    ForeignKey,
    Integer,
    String,
    TIMESTAMP,
    func,
)

from src.core.database import Base


class WebAccessibilityCrawlsModel(Base):
    __tablename__ = "web_accessibility_crawls"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    website_id = Column(BigInteger, ForeignKey("web_accessibility_websites.id"), nullable=False)
    discovery_source = Column(String(20), nullable=True)  # "sitemap" | "links"
    max_pages = Column(Integer, nullable=True)
    pages_discovered = Column(Integer, nullable=False, default=0)
    created_at = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(),
            onupdate=func.current_timestamp())

    def to_dict(self):
        return {
            "id": self.id,
            "website_id": self.website_id,
            "discovery_source": self.discovery_source,
            "max_pages": self.max_pages,
            "pages_discovered": self.pages_discovered,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
