from typing import Optional

from sqlalchemy.orm import Session

from src.core.logger import get_logger
from src.modules.accessibility_web.models.web_accessibility_websites_model import (
    WebAccessibilityWebsiteModel,
)

logger = get_logger(__name__)


class WebsiteService:

    def create_website(
        self,
        db: Session,
        base_url: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        environment: str = "PRODUCTION",
        crawl_enabled: bool = False,
        crawl_frequency: Optional[str] = None,
        authentication_required: bool = False,
        authentication_type: Optional[str] = None,
    ) -> WebAccessibilityWebsiteModel:
        """Register a new website. Raises ValueError on bad/duplicate input."""
        if not base_url or not base_url.strip():
            raise ValueError("base_url is required")

        existing = (
            db.query(WebAccessibilityWebsiteModel)
            .filter(WebAccessibilityWebsiteModel.base_url == base_url)
            .first()
        )
        if existing:
            raise ValueError(f"A website with base_url '{base_url}' is already registered")

        website = WebAccessibilityWebsiteModel(
            name=name,
            base_url=base_url,
            description=description,
            environment=environment,
            crawl_enabled=crawl_enabled,
            crawl_frequency=crawl_frequency,
            authentication_required=authentication_required,
            authentication_type=authentication_type,
        )
        db.add(website)
        db.commit()
        db.refresh(website)
        logger.info("Registered website id=%s base_url=%s", website.id, website.base_url)
        return website

    def get_all_websites(
        self,
        db: Session,
        environment: Optional[str] = None,
        crawl_enabled: Optional[bool] = None,
    ) -> list[WebAccessibilityWebsiteModel]:
        """List websites, optionally filtered by environment and/or crawl_enabled."""
        query = db.query(WebAccessibilityWebsiteModel)

        if environment is not None:
            query = query.filter(WebAccessibilityWebsiteModel.environment == environment)

        if crawl_enabled is not None:
            query = query.filter(WebAccessibilityWebsiteModel.crawl_enabled == crawl_enabled)

        return query.order_by(WebAccessibilityWebsiteModel.id.asc()).all()

    def get_website_by_id(
        self, db: Session, website_id: int
    ) -> Optional[WebAccessibilityWebsiteModel]:
        """Get a single website by its ID."""
        return (
            db.query(WebAccessibilityWebsiteModel)
            .filter(WebAccessibilityWebsiteModel.id == website_id)
            .first()
        )

    def update_website(
        self,
        db: Session,
        website_id: int,
        **updates,
    ) -> Optional[WebAccessibilityWebsiteModel]:
        """Update a website. Only keys present with a non-None value are applied."""
        website = self.get_website_by_id(db, website_id)
        if not website:
            return None

        if "base_url" in updates and updates["base_url"] is not None:
            new_base_url = updates["base_url"]
            duplicate = (
                db.query(WebAccessibilityWebsiteModel)
                .filter(
                    WebAccessibilityWebsiteModel.base_url == new_base_url,
                    WebAccessibilityWebsiteModel.id != website_id,
                )
                .first()
            )
            if duplicate:
                raise ValueError(f"A website with base_url '{new_base_url}' is already registered")

        for field, value in updates.items():
            if value is not None and hasattr(website, field):
                setattr(website, field, value)

        db.commit()
        db.refresh(website)
        logger.info("Updated website id=%s", website.id)
        return website

    def delete_website(self, db: Session, website_id: int) -> bool:
        """Delete a website by ID."""
        website = self.get_website_by_id(db, website_id)
        if not website:
            return False

        db.delete(website)
        db.commit()
        logger.info("Deleted website id=%s", website_id)
        return True
