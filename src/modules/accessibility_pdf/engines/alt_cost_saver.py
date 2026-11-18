#!/usr/bin/env python3
"""
alt_cost_saver.py

Cost-reduction layer for alt_vision_suggester. Implements the hybrid strategy:

    decorative pre-filter  -> mark Artifact, NO api call
    caption reuse          -> use printed caption as Alt, NO api call
    disk cache             -> identical image+prompt+model, NO api call
    adaptive downscale     -> render only as many pixels as the model needs
    cheaper default model  -> Haiku instead of Opus

Everything here is deterministic (pikepdf/PyMuPDF/stdlib). No network, no LLM.
Each piece is independently switchable so you can tune the quality/cost tradeoff.

Env knobs (all optional):
    ORION_ALT_MAX_EDGE      longest crop edge in px            (default 1024)
    ORION_ALT_BASE_DPI      never render above this dpi        (default 200)
    ORION_ALT_CACHE_DIR     cache location                     (default .alt_cache)
    ORION_ALT_CACHE         "0" disables the cache             (default on)
    ORION_ALT_CAPTION_REUSE "0" disables caption reuse         (default on)
    ORION_ALT_DECOR_FILTER  "0" disables decorative pre-filter (default on)

NOTE on caption reuse and PDF/UA: a screen reader announces a visible caption
separately from /Alt, so alt text identical to the caption is redundant. Reuse is
therefore applied only when the caption is descriptive enough to stand alone, and
it is recorded with source="caption-reuse" so you can audit or disable it. When
you want maximum quality, set ORION_ALT_CAPTION_REUSE=0 and let the model write
the complementary sentence instead.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

import fitz  # PyMuPDF

# Load repo-root .env into os.environ BEFORE reading any ORION_ALT_* constants
# below — otherwise .env settings (e.g. ORION_ALT_CACHE_DIR) are ignored and the
# defaults win. See env_bootstrap.py for why this is needed.
try:
    from .env_bootstrap import load_repo_dotenv
except ImportError:
    from env_bootstrap import load_repo_dotenv
load_repo_dotenv()


# ---------------------------------------------------------------- config ----

def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


def _env_on(name: str, default: bool = True) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() not in ("0", "false", "no", "off")


MAX_EDGE = _env_int("ORION_ALT_MAX_EDGE", 1024)
BASE_DPI = _env_int("ORION_ALT_BASE_DPI", 200)
CACHE_DIR = os.environ.get("ORION_ALT_CACHE_DIR", ".alt_cache")
CACHE_ON = _env_on("ORION_ALT_CACHE", True)
CAPTION_REUSE_ON = _env_on("ORION_ALT_CAPTION_REUSE", True)
DECOR_FILTER_ON = _env_on("ORION_ALT_DECOR_FILTER", True)


# ------------------------------------------------------- adaptive render ----

def adaptive_dpi(bbox_w_pts: float, bbox_h_pts: float,
                 max_edge: int = MAX_EDGE, base_dpi: int = BASE_DPI) -> int:
    """
    DPI that renders this bbox with its longest edge at ~max_edge px, capped at
    base_dpi so we never upscale. Rendering small beats rendering big then
    shrinking: fewer pixels to produce AND fewer image tokens to bill.
    """
    longest_pts = max(float(bbox_w_pts), float(bbox_h_pts))
    if longest_pts <= 0:
        return base_dpi
    dpi_needed = (max_edge * 72.0) / longest_pts
    return max(24, min(int(base_dpi), int(dpi_needed)))


# ------------------------------------------------------------- decorative ---

# Size thresholds for "this is an icon/badge, not content".
# Tuned against CBSE/NCERT textbook layouts, where section-header badges
# ("Exploratory Activity", "Think and Discuss") land around 44-50pt square.
# Raise ORION_ALT_ICON_MAX_PTS if your titles use larger decorative art;
# lower it if you find real content being artifacted.
_TINY_PTS = float(_env_int("ORION_ALT_TINY_PTS", 28))          # longest edge
_ICON_MAX_PTS = float(_env_int("ORION_ALT_ICON_MAX_PTS", 60))  # icon-rule cap
_TINY_AREA_PTS2 = float(_env_int("ORION_ALT_ICON_AREA", 2600))  # ~51x51 pt


def looks_decorative(png_bytes: bytes,
                     bbox_w_pts: float, bbox_h_pts: float,
                     caption: str = "", known_content: bool = False) -> tuple[bool, str]:
    """
    Cheap, conservative decorative test. Returns (is_decorative, reason).

    Conservative on purpose: a false "decorative" silently hides real content
    from screen-reader users, which is a worse failure than paying for one API
    call. So anything with a caption, or flagged known_content, is never
    decorative here, and the pixel test demands near-uniformity.
    """
    if known_content:
        return False, ""
    if caption.strip():
        return False, ""

    longest = max(bbox_w_pts, bbox_h_pts)
    area = bbox_w_pts * bbox_h_pts
    if longest > 0 and longest < _TINY_PTS:
        return True, f"tiny figure ({bbox_w_pts:.0f}x{bbox_h_pts:.0f}pt)"
    if 0 < area < _TINY_AREA_PTS2 and longest < _ICON_MAX_PTS:
        return True, f"small icon-sized figure ({area:.0f}pt^2)"

    # Near-uniform pixels => rule, bar, solid swatch, blank box.
    try:
        pix = fitz.Pixmap(png_bytes)
        if pix.width * pix.height == 0:
            return True, "empty raster"
        step = max(1, (pix.width * pix.height) // 4000)  # sample ~4k pixels
        n = pix.n
        samples = set()
        buf = pix.samples
        total = pix.width * pix.height
        for idx in range(0, total, step):
            off = idx * n
            samples.add(bytes(buf[off:off + min(3, n)]))
            if len(samples) > 12:      # clearly varied -> not decorative
                return False, ""
        if len(samples) <= 3:
            return True, f"near-uniform raster ({len(samples)} distinct colours)"
    except Exception:
        pass  # never fail the pipeline on a heuristic

    return False, ""


# ---------------------------------------------------------- caption reuse ---

# A caption that can stand alone as alt text: enough words, not just a label
# fragment, not a bare figure number.
_BARE_LABEL = re.compile(r"^(fig(ure)?\.?\s*\d+[a-z]?|table\s*\d+|image|photo)\W*$", re.I)


def caption_is_sufficient(caption: str, min_words: int = 2) -> bool:
    """True if the printed caption is descriptive enough to serve as /Alt."""
    c = (caption or "").strip()
    if not c or _BARE_LABEL.match(c):
        return False
    words = [w for w in re.split(r"\s+", c) if any(ch.isalpha() for ch in w)]
    if len(words) < min_words:
        return False
    # char-spaced OCR junk, e.g. "h C a p t e r 2"
    singles = sum(1 for w in words if len(w) == 1)
    if len(words) >= 4 and singles / len(words) >= 0.6:
        return False
    return True


def caption_as_alt(caption: str) -> str:
    """Normalise a caption into an alt string."""
    c = re.sub(r"\s+", " ", (caption or "").strip()).strip(" .;:,")
    return c


# ----------------------------------------------------------------- cache ----

class AltCache:
    """
    Disk cache keyed on sha256(image bytes + prompt + model). Survives process
    restarts, so re-running the same PDF during debugging costs nothing.
    """

    def __init__(self, cache_dir: str = CACHE_DIR, enabled: bool = CACHE_ON):
        self.enabled = bool(enabled)
        self.dir = Path(cache_dir)
        self.hits = 0
        self.misses = 0
        self.writes = 0
        if self.enabled:
            try:
                self.dir.mkdir(parents=True, exist_ok=True)
            except Exception:
                self.enabled = False

    @staticmethod
    def key(png_bytes: bytes, prompt: str, model: str) -> str:
        h = hashlib.sha256()
        h.update(png_bytes)
        h.update(b"\x00")
        h.update(prompt.encode("utf-8", "replace"))
        h.update(b"\x00")
        h.update(model.encode("utf-8", "replace"))
        return h.hexdigest()

    def _path(self, k: str) -> Path:
        return self.dir / f"{k[:2]}" / f"{k}.json"

    def get(self, k: str):
        if not self.enabled:
            return None
        p = self._path(k)
        try:
            if p.exists():
                with p.open(encoding="utf-8") as fh:
                    self.hits += 1
                    return json.load(fh).get("alt")
        except Exception:
            pass
        self.misses += 1
        return None

    def put(self, k: str, alt: str) -> None:
        if not self.enabled:
            return
        p = self._path(k)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8") as fh:
                json.dump({"alt": alt}, fh, ensure_ascii=False)
            os.replace(tmp, p)   # atomic; safe on Windows
            self.writes += 1
        except Exception:
            pass

    def stats(self) -> dict:
        return {"enabled": self.enabled, "hits": self.hits,
                "misses": self.misses, "writes": self.writes}


# ------------------------------------------------------------- reporting ----

class SavingsLedger:
    """Counts how each figure was resolved, so a run reports its own cost."""

    def __init__(self):
        self.counts = {"llm": 0, "cache": 0, "caption": 0, "decorative": 0, "skipped": 0}

    def bump(self, kind: str) -> None:
        self.counts[kind] = self.counts.get(kind, 0) + 1

    def summary(self) -> dict:
        total = sum(self.counts.values())
        billed = self.counts.get("llm", 0)
        avoided = total - billed - self.counts.get("skipped", 0)
        pct = (100.0 * avoided / total) if total else 0.0
        return {**self.counts, "total": total, "api_calls": billed,
                "calls_avoided": avoided, "avoided_pct": round(pct, 1)}
