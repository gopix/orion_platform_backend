import hashlib

from sqlalchemy import (
    BigInteger,
    Column,
    ForeignKey,
    String,
    TIMESTAMP,
    UniqueConstraint,
    func,
)

from src.core.database import Base


def hash_page_url(url: str) -> str:
    """
    SHA256 hex digest of a page url, used as the uniqueness key for
    web_accessibility_pages instead of the raw url column.

    Why not UNIQUE(website_id, url) directly: MySQL/InnoDB caps a total
    index key at 3072 bytes; url is VARCHAR(2048), and in utf8mb4 (4 bytes/
    char) that alone is 8192 bytes - CREATE TABLE fails with error 1071
    ("Specified key was too long") no matter the row format. Hashing gives
    a fixed 64-byte key (well under the limit) while url itself stays a
    full VARCHAR(2048), so long URLs (query strings, tracking params,
    etc.) are never truncated or rejected. Both scan_service.py's
    _get_or_create_page() and scripts/migrate_web_accessibility_pages.py's
    backfill call this - keep it here as the single source of truth so
    the two never compute the hash differently.
    """
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


class WebAccessibilityPagesModel(Base):
    """
    A single page on a registered website - the persistent entity a Scan is
    run against and an Issue is ultimately scoped to:

        Website 1:N Page 1:N Scan 1:N Issue

    Created implicitly by scan_service.create_scan()'s get-or-create the
    first time a given (website_id, url) is scanned - there's no separate
    "add a page" endpoint yet, matching how a page naturally comes into
    being today (someone scans a URL). A future crawler that discovers
    links off a website's base_url would create these the same way, before
    a scan ever runs against them - see scan_service.py's module docstring.

    Uniqueness is enforced on (website_id, url_hash), not (website_id,
    url) - see hash_page_url()'s docstring above for why. url_hash is
    populated alongside url wherever a Page is created/looked up; it is
    not meant to be read/displayed on its own, url is what callers use.
    """

    __tablename__ = "web_accessibility_pages"
    __table_args__ = (
        UniqueConstraint("website_id", "url_hash", name="uq_web_accessibility_pages_website_url_hash"),
    )

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    website_id = Column(BigInteger, ForeignKey("web_accessibility_websites.id"), nullable=False)
    url = Column(String(2048), nullable=False)
    url_hash = Column(String(64), nullable=False)
    created_at = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(),
            onupdate=func.current_timestamp())

    def to_dict(self):
        return {
            "id": self.id,
            "website_id": self.website_id,
            "url": self.url,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
