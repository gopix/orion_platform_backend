"""
scan_schema.py – Pydantic request schema for POST /websites/{id}/scan.
"""

from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class ScanCreateRequest(BaseModel):
    """
    POST /websites/{website_id}/scan body. Two modes:

      - single page (default - all_pages omitted or false): url is
        required, queues exactly that one page via
        ScanService.create_scan().
      - all_pages=true: discovers and queues every page on the site
        instead - sitemap-first, falling back to homepage link-scraping
        if there's no usable sitemap (see ScanService.crawl_website()).
        url is NOT required/used in this mode: discovery always starts
        from the website's own registered base_url, never an arbitrary
        caller-supplied url - there used to be a separate POST
        /websites/{id}/crawl endpoint for this; folded in here instead so
        there's one endpoint, one way to queue scans, rather than two
        endpoints whose only real difference was "one url vs many".
        max_pages caps how many pages get queued in this mode (default
        20, hard max 100 - le=100 here gives an immediate 422 on a
        too-large request; ScanService.crawl_website() also clamps as a
        defense-in-depth backstop for any other caller).

    Either way, the response is 202 immediately with the actual fetch(es)
    queued as FastAPI BackgroundTasks - this schema/endpoint never blocks
    on the page fetch(es) themselves finishing, only (in all_pages mode)
    on the synchronous discovery step (sitemap fetch, or the seed-page
    fetch+parse) needed to know what to queue in the first place.
    """
    url: Optional[str] = Field(default=None, min_length=1, max_length=2048)
    all_pages: bool = False
    max_pages: Optional[int] = Field(default=None, ge=1, le=100)

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("url must start with http:// or https://")
        return v

    @model_validator(mode="after")
    def check_url_required_unless_all_pages(self) -> "ScanCreateRequest":
        if not self.all_pages and not self.url:
            raise ValueError("url is required unless all_pages is true")
        return self
