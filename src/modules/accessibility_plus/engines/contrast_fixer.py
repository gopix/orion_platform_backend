"""
contrast_fixer.py  --  WCAG 1.4.3 contrast post-processing step.

Two bugs fixed vs the original version:
  1. zlib bug: pikepdf stream.write() stores data AS-IS but sets the /Filter
     header.  Data MUST be zlib.compress()-ed first or viewers get garbage.
  2. White-only check: some colours pass 4.5:1 against white but fail against
     near-white table-row backgrounds.  We now extract all light colours from
     the same content stream and check against the worst-case background.
"""
from __future__ import annotations

import logging
import re
import zlib
from pathlib import Path
from typing import List, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# WCAG helpers
# ---------------------------------------------------------------------------

def _linearise(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _luminance(r: float, g: float, b: float) -> float:
    return 0.2126 * _linearise(r) + 0.7152 * _linearise(g) + 0.0722 * _linearise(b)


def _contrast(c1: Tuple[float, float, float],
              c2: Tuple[float, float, float]) -> float:
    l1, l2 = _luminance(*c1), _luminance(*c2)
    if l1 < l2:
        l1, l2 = l2, l1
    return (l1 + 0.05) / (l2 + 0.05)


def _darken_to_contrast(r, g, b, bg=(1.0, 1.0, 1.0), target=4.5):
    """Binary-search the max scale factor s in [0,1] that meets target contrast.
    Uses target+0.01 internally so floating-point rounding does not leave the
    result fractionally below the nominal threshold."""
    safe_target = target + 0.01
    if _contrast((r, g, b), bg) >= safe_target:
        return r, g, b
    lo, hi = 0.0, 1.0
    for _ in range(40):
        s = (lo + hi) / 2.0
        if _contrast((r * s, g * s, b * s), bg) >= safe_target:
            lo = s
        else:
            hi = s
    return r * lo, g * lo, b * lo


def _fmt(v: float) -> str:
    return f"{v:.6f}"


# ---------------------------------------------------------------------------
# Background detection
# ---------------------------------------------------------------------------

_RG_RE = re.compile(rb"([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+rg")
_G_RE  = re.compile(rb"([\d.]+)\s+g(?=\s|$)")


def _bg_candidates(data: bytes) -> List[Tuple[float, float, float]]:
    """Return light colours (lum > 0.60) found in the stream, plus white."""
    seen = set()
    result = [(1.0, 1.0, 1.0)]
    for m in _RG_RE.finditer(data):
        r, g, b = float(m.group(1)), float(m.group(2)), float(m.group(3))
        key = (round(r, 4), round(g, 4), round(b, 4))
        if key not in seen and _luminance(r, g, b) > 0.60:
            result.append((r, g, b))
            seen.add(key)
    for m in _G_RE.finditer(data):
        v = float(m.group(1))
        key = (round(v, 4),) * 3
        if key not in seen and _luminance(v, v, v) > 0.60:
            result.append((v, v, v))
            seen.add(key)
    return result


# ---------------------------------------------------------------------------
# Stream patcher
# ---------------------------------------------------------------------------

def _patch_stream(data: bytes, target_ratio: float, replacements: list):
    """
    Patch non-compliant fill-colour operators in one decompressed stream.
    Checks contrast against every light background found in the same stream.
    Returns (patched_bytes, n_changes).
    """
    changes = 0
    bgs = _bg_candidates(data)

    def rep_rg(m):
        nonlocal changes
        r, g, b = float(m.group(1)), float(m.group(2)), float(m.group(3))
        lum = _luminance(r, g, b)
        if lum < 0.05 or lum > 0.50:
            return m.group(0)
        worst_ratio = min(_contrast((r, g, b), bg) for bg in bgs)
        if worst_ratio >= target_ratio:
            return m.group(0)
        worst_bg = min(bgs, key=lambda bg: _contrast((r, g, b), bg))
        nr, ng, nb = _darken_to_contrast(r, g, b, bg=worst_bg, target=target_ratio)
        replacements.append({
            "old": f"rgb({r:.4f},{g:.4f},{b:.4f})",
            "new": f"rgb({nr:.4f},{ng:.4f},{nb:.4f})",
            "old_contrast": round(worst_ratio, 2),
            "new_contrast": round(_contrast((nr, ng, nb), worst_bg), 2),
            "background": f"rgb({worst_bg[0]:.3f},{worst_bg[1]:.3f},{worst_bg[2]:.3f})",
        })
        changes += 1
        return f"{_fmt(nr)} {_fmt(ng)} {_fmt(nb)} rg".encode("latin-1")

    def rep_g(m):
        nonlocal changes
        v = float(m.group(1))
        lum = _luminance(v, v, v)
        if lum < 0.05 or lum > 0.50:
            return m.group(0)
        worst_ratio = min(_contrast((v, v, v), bg) for bg in bgs)
        if worst_ratio >= target_ratio:
            return m.group(0)
        worst_bg = min(bgs, key=lambda bg: _contrast((v, v, v), bg))
        nv, _, _ = _darken_to_contrast(v, v, v, bg=worst_bg, target=target_ratio)
        replacements.append({
            "old": f"gray({v:.4f})",
            "new": f"gray({nv:.4f})",
            "old_contrast": round(worst_ratio, 2),
            "new_contrast": round(_contrast((nv, nv, nv), worst_bg), 2),
            "background": f"rgb({worst_bg[0]:.3f},{worst_bg[1]:.3f},{worst_bg[2]:.3f})",
        })
        changes += 1
        return f"{_fmt(nv)} g".encode("latin-1")

    data = _RG_RE.sub(rep_rg, data)
    data = _G_RE.sub(rep_g, data)
    return data, changes


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fix_text_contrast(pdf_path, target_ratio: float = 4.5) -> dict:
    """
    Fix text colour contrast in-place.  Checks against all light backgrounds
    detected in each content stream, not just pure white.

    Returns dict: pages_modified, total_changes, replacements, success.
    """
    import pikepdf

    pdf_path = Path(pdf_path)
    print(f"[contrast_fixer] fix_text_contrast: {pdf_path}  exists={pdf_path.exists()}")

    try:
        pdf = pikepdf.open(pdf_path, allow_overwriting_input=True)
    except Exception as e:
        print(f"[contrast_fixer] ERROR opening PDF: {e}")
        return {"pages_modified": 0, "total_changes": 0, "replacements": [], "success": False}

    pages_modified = 0
    total_changes = 0
    all_replacements: List[dict] = []

    for page_num, page in enumerate(pdf.pages):
        if "/Contents" not in page:
            continue

        contents = page["/Contents"]
        page_changes = 0
        streams = contents if isinstance(contents, pikepdf.Array) else [contents]

        for stream in streams:
            try:
                # Decompress stream.
                # Fallback handles streams corrupted by the old zlib bug
                # (FlateDecode header but uncompressed data).
                try:
                    raw = stream.read_bytes()
                except Exception:
                    raw_buf = bytes(stream.get_raw_stream_buffer())
                    try:
                        raw = zlib.decompress(raw_buf)
                    except Exception:
                        raw = raw_buf

                patched, n = _patch_stream(raw, target_ratio, all_replacements)

                if n > 0:
                    # CRITICAL: compress manually before write.
                    # pikepdf.stream.write() stores bytes AS-IS but sets /Filter
                    # to FlateDecode -- so we must compress ourselves first.
                    compressed = zlib.compress(patched, level=6)
                    stream.write(compressed, filter=pikepdf.Name("/FlateDecode"))
                    page_changes += n

            except Exception as e:
                print(f"[contrast_fixer]   page {page_num + 1} stream error: {e}")

        if page_changes:
            pages_modified += 1
            total_changes += page_changes
            print(f"[contrast_fixer]   page {page_num + 1}: {page_changes} colour(s) fixed")

    if total_changes > 0:
        tmp = pdf_path.with_suffix(".contrast_tmp.pdf")
        pdf.save(tmp)
        pdf.close()
        import shutil
        shutil.move(str(tmp), str(pdf_path))
        print(f"[contrast_fixer] Saved: {total_changes} change(s) on {pages_modified} page(s)")
    else:
        pdf.close()
        print("[contrast_fixer] No contrast issues found — file unchanged")

    seen: set = set()
    for rep in all_replacements:
        key = rep["old"]
        if key not in seen:
            seen.add(key)
            logger.info(
                "contrast_fixer: %s -> %s  (%.2f:1 -> %.2f:1 vs %s)",
                rep["old"], rep["new"],
                rep["old_contrast"], rep["new_contrast"],
                rep.get("background", "white"),
            )
            print(
                f"[contrast_fixer]   {rep['old']} -> {rep['new']}"
                f"  ({rep['old_contrast']}:1 -> {rep['new_contrast']}:1"
                f"  vs {rep.get('background', 'white')})"
            )

    return {
        "pages_modified": pages_modified,
        "total_changes": total_changes,
        "replacements": all_replacements,
        "success": True,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    import json
    import shutil
    import logging

    if len(sys.argv) not in (2, 3):
        print("Usage: python contrast_fixer.py <input.pdf> [output.pdf]")
        sys.exit(1)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    src = Path(sys.argv[1])
    dst = Path(sys.argv[2]) if len(sys.argv) == 3 else None

    if dst and dst != src:
        shutil.copy2(str(src), str(dst))
        result = fix_text_contrast(str(dst))
    else:
        result = fix_text_contrast(str(src))

    print(json.dumps(result, indent=2))
