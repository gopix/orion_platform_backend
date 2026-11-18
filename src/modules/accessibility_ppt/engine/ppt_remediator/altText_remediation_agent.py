"""
altText_remediation_agent.py
============================
AltTextRemediationAgent — remediates image alt-text issues found by the PPT
ImageAgent, mutating context["presentation"] in place.

Rules handled (supported_rules)
    PPT-IMAGE-001  Missing alt text      -> generate/apply alt
    PPT-IMAGE-002  Non-descriptive alt   -> replace with real alt
    PPT-IMAGE-003  Decorative + alt      -> clear the redundant alt (deterministic)

How alt text is produced (in priority order), per image:
    1. Supplied decision  — context["alt_decisions"][(slide_index, shape_id)]
                            (human-authored/pre-approved text always wins)
    2. Vision             — the embedded image BLOB is sent to a vision model
                            (Claude by default). Unlike PDFs, PPT images are
                            already raster blobs, so no rendering is needed.
    3. Skip               — if neither is available (e.g. no API key), the image
                            is left unchanged and reported for manual review,
                            never stamped with a placeholder.

Cost care: decorative images are skipped, identical image blobs are described
once (cached by content hash), and only supported raster types are sent.
Injection: pass context["vision_fn"] = fn(blob, media_type, api_key, model)->str
to unit-test without network access.
"""
from __future__ import annotations

import base64
import hashlib
import os
import re
from pathlib import Path
from typing import Any

from src.modules.accessibility_ppt.engine.ppt_remediator.base_remediation_agent import (
    BasePPTRemediationAgent,
    RemediationResult,
)

_VISION_MEDIA = {"image/png", "image/jpeg", "image/gif", "image/webp"}
_DEFAULT_MODEL = os.environ.get("orion-claude-model", "claude-haiku-4-5-20251001")

# Weak-alt heuristics (mirror the validator's ImageAgent).
_GENERIC_ALT = {"image", "picture", "photo", "graphic", "img", "pic", "icon",
                "screenshot", "untitled", "figure", "diagram", "shape", "object"}
_IMG_EXT = re.compile(r"\.(png|jpe?g|gif|bmp|svg|tiff?|webp|emf|wmf|heic)\b", re.I)
_DEFAULT_NAME = re.compile(r"^\W*(picture|image|content placeholder|google shape|"
                           r"shape|object|graphic|placeholder)\s*[\d;:_-]*$", re.I)

_PROMPT = (
    "You are writing PowerPoint alt text for a screen-reader user. In ONE concise "
    "sentence (max ~25 words), describe what this image shows and its point. "
    "Do NOT start with 'image of'/'picture of'. Describe only what is visible; if "
    "text is too small to read, describe the image type without inventing values. "
    "Return only the sentence."
)


def _key_from_dotenv() -> str:
    """Read ANTHROPIC_API_KEY from repo-root .env (the app doesn't load it into env)."""
    for p in (Path(__file__).resolve().parents[5] / ".env", Path.cwd() / ".env"):
        try:
            if not p.exists():
                continue
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.lower().startswith("ANTHROPIC_API_KEY") and ("=" in line or ":" in line):
                    sep = "=" if "=" in line else ":"
                    v = line.split(sep, 1)[1].strip().strip('"').strip("'")
                    if v:
                        return v
        except Exception:
            continue
    return ""


class AltTextRemediationAgent(BasePPTRemediationAgent):
    """Fix image alt-text issues in a presentation."""

    agent_name = "PPT Alt-Text Remediation Agent"
    supported_rules = {"PPT-IMAGE-001", "PPT-IMAGE-002", "PPT-IMAGE-003"}

    # ---------------------------------------------------------------- dispatch
    def remediate(self, issue: dict[str, Any],
                  context: dict[str, Any]) -> RemediationResult:
        rule_id = (issue or {}).get("rule_id", "PPT-IMAGE-001")
        try:
            prs = self._presentation(context)
        except ValueError as exc:
            return self._result(rule_id, False, "alt_text", error=str(exc))

        try:
            if rule_id == "PPT-IMAGE-003":
                return self._fix_decorative_contradiction(prs, rule_id)
            return self._fix_missing_or_weak_alt(prs, context, rule_id)
        except Exception as exc:            # never let one image abort the job
            return self._result(rule_id, False, "alt_text", error=str(exc))

    # ---------------------------------------------------------- weak-alt test
    @classmethod
    def _alt_is_weak(cls, alt: str) -> bool:
        a = (alt or "").strip()
        low = a.casefold()
        if len(a) < 5:
            return True
        if low in _GENERIC_ALT:
            return True
        if _IMG_EXT.search(a):
            return True
        if _DEFAULT_NAME.match(a):
            return True
        return False

    def _pictures_needing_alt(self, prs):
        for si, shape in self._iter_shapes(prs):
            if not self._is_picture(shape) or self._is_decorative(shape):
                continue
            alt = self._get_alt(shape)
            if not alt or self._alt_is_weak(alt):
                yield si, shape

    # ------------------------------------------------------------- 003 clear
    def _fix_decorative_contradiction(self, prs, rule_id) -> RemediationResult:
        changes = []
        for si, shape in self._iter_shapes(prs):
            if self._is_picture(shape) and self._is_decorative(shape) and self._get_alt(shape):
                if self._clear_alt(shape):
                    changes.append(f"slide {si + 1}: cleared alt on decorative "
                                   f"image '{getattr(shape, 'name', 'image')}'")
        return self._result(rule_id, True, "clear_decorative_alt", changes_made=changes)

    # ------------------------------------------------------- 001/002 set alt
    def _fix_missing_or_weak_alt(self, prs, context, rule_id) -> RemediationResult:
        decisions = context.get("alt_decisions") or {}
        vision_fn = context.get("vision_fn") or self._claude_describe
        have_vision_fn = context.get("vision_fn") is not None
        api_key = (context.get("api_key") or os.environ.get("ANTHROPIC_API_KEY", "")
                   or _key_from_dotenv())
        model = context.get("model") or _DEFAULT_MODEL
        can_vision = have_vision_fn or bool(api_key)

        cache: dict[str, str] = {}
        changes: list[str] = []
        skipped: list[int] = []

        for si, shape in self._pictures_needing_alt(prs):
            new_alt = self._decision_for(decisions, si, shape)

            if not new_alt and can_vision:
                new_alt = self._describe_via_vision(shape, vision_fn, api_key,
                                                    model, cache)

            if new_alt and self._set_alt(shape, new_alt):
                changes.append(f"slide {si + 1}: set alt '{new_alt[:50]}'")
            else:
                skipped.append(si + 1)

        err = None
        if skipped:
            err = (f"{len(skipped)} image(s) on slide(s) "
                   f"{', '.join(map(str, sorted(set(skipped))))} still need alt "
                   f"(no decision and no vision available) — manual review")
        # success = the pass ran cleanly; leftover images are reported, not fatal.
        return self._result(rule_id, True, "set_image_alt",
                            changes_made=changes, error=err)

    # ---------------------------------------------------------- vision utils
    @staticmethod
    def _decision_for(decisions: dict, si: int, shape) -> str:
        if not decisions:
            return ""
        sid = getattr(shape, "shape_id", None)
        for key in ((si, sid), f"{si}:{sid}", f"{si + 1}:{sid}", sid):
            if key in decisions and isinstance(decisions[key], str):
                return decisions[key].strip()
        return ""

    def _describe_via_vision(self, shape, vision_fn, api_key, model, cache) -> str:
        try:
            img = shape.image
            blob, media = img.blob, img.content_type
        except Exception:
            return ""                       # non-embedded / vector: can't send
        if media not in _VISION_MEDIA:
            return ""
        h = hashlib.sha256(blob).hexdigest()
        if h in cache:
            return cache[h]
        try:
            alt = (vision_fn(blob, media, api_key, model) or "").strip()
        except Exception:
            alt = ""
        alt = self._tidy(alt)
        if alt:
            cache[h] = alt
        return alt

    @staticmethod
    def _tidy(s: str) -> str:
        s = " ".join((s or "").split())
        s = re.sub(r"^(an?\s+)?(image|picture|photo|graphic)\s+(of|showing)\s+",
                   "", s, flags=re.I)
        if s and s[0].islower():
            s = s[0].upper() + s[1:]
        if s and not s.endswith((".", "!", "?")):
            s += "."
        return s[:250]

    @staticmethod
    def _claude_describe(blob: bytes, media_type: str, api_key: str, model: str) -> str:
        """Default vision function: describe an image blob with Claude."""
        if not api_key:
            return ""
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=model, max_tokens=200,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64",
                 "media_type": media_type,
                 "data": base64.b64encode(blob).decode()}},
                {"type": "text", "text": _PROMPT},
            ]}])
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
