#!/usr/bin/env python3
"""
alt_vision_suggester.py
=======================
Bridges alt_text_sanitizer -> alt_apply for the "no alt, no caption" figures.

alt_text_sanitizer (Step 11) writes "[TO BE DESCRIBED]" and lists those
figures in <stem>_alt_needs.json under "needs_human". This module reads that
list, crops each figure from the PDF, asks a Claude vision model for a concise
alt description (or "DECORATIVE"), and writes a decisions.json in the exact
schema alt_apply (Step 12) already consumes:

    [ {"page": 2, "mcid": 29, "alt": "..."},
      {"page": 16, "mcid": 22, "decorative": true}, ... ]

Then the pipeline runs alt_apply with this file. Every vision-authored entry
carries source="vision", verified=false so the QA gate can still surface them
for optional human review — they are a defensible default, not a rubber stamp.

Usage:
    python alt_vision_suggester.py in.pdf in_alt_needs.json decisions.json
Env: ANTHROPIC_API_KEY  (same key var the rest of the engine uses)
"""
from __future__ import annotations
import os, sys, json, base64, re, time, argparse
from pathlib import Path

import pikepdf
import fitz  # PyMuPDF

try:
    from .mcid_geometry import document_mcid_boxes
except ImportError:
    from mcid_geometry import document_mcid_boxes

try:
    import anthropic as _anthropic
    _HAS_ANTHROPIC = True
except ImportError:
    _anthropic = None
    _HAS_ANTHROPIC = False

try:
    from .alt_cost_saver import (AltCache, SavingsLedger, adaptive_dpi,
                                 caption_as_alt, caption_is_sufficient,
                                 looks_decorative, CAPTION_REUSE_ON,
                                 DECOR_FILTER_ON)
except ImportError:
    from alt_cost_saver import (AltCache, SavingsLedger, adaptive_dpi,
                                caption_as_alt, caption_is_sufficient,
                                looks_decorative, CAPTION_REUSE_ON,
                                DECOR_FILTER_ON)

# Ensure repo-root .env is loaded so orion-claude-model / pricing overrides work.
try:
    from .env_bootstrap import load_repo_dotenv
except ImportError:
    from env_bootstrap import load_repo_dotenv
load_repo_dotenv()

# Default to Haiku: describing a figure in one sentence does not need Opus.
# Override with orion-claude-model to go back to a larger model.
MODEL = os.environ.get("orion-claude-model", "claude-haiku-4-5-20251001")
DPI = 200
MARGIN = 6          # pts around the figure bbox
CTX_PAD = 130       # pts of surrounding text to send as context

# LLM cost accounting. Defaults are Claude Haiku 4.5 list pricing:
# $1.00 / million input tokens, $5.00 / million output tokens (Jul 2026).
# Override per-run via .env if you switch models or pricing changes.
PRICE_IN_PER_MTOK = float(os.environ.get("ORION_ALT_PRICE_IN_PER_MTOK", "1.0"))
PRICE_OUT_PER_MTOK = float(os.environ.get("ORION_ALT_PRICE_OUT_PER_MTOK", "5.0"))

# Side channel: _call_claude_alt writes the token usage of its most recent call
# here so suggest() can meter cost without changing the vision_fn return type
# (custom/test vision_fns simply leave it at zero).
_LAST_USAGE = {"input_tokens": 0, "output_tokens": 0}


def _usd(in_tok: int, out_tok: int) -> float:
    return (in_tok / 1_000_000.0) * PRICE_IN_PER_MTOK + \
           (out_tok / 1_000_000.0) * PRICE_OUT_PER_MTOK


def _key_from_dotenv():
    """Fall back to the repo-root .env when the key isn't in os.environ.
    Mirrors the pipeline's own .env parsing (repo-root/.env), because the
    app does not do a global load_dotenv() — the key lives on disk, not in
    this process's environment."""
    candidates = []
    try:
        candidates.append(Path(__file__).resolve().parents[4] / ".env")
    except Exception:
        pass
    candidates.append(Path.cwd() / ".env")
    for p in candidates:
        try:
            if not p.exists():
                continue
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                low = line.lower()
                if "orion-" in low and "key" in low:
                    for sep in ("=", ":"):
                        if sep in line:
                            v = line.split(sep, 1)[1].strip().strip('"').strip("'")
                            if v:
                                return v
        except Exception:
            continue
    return ""


def _resolve_key(explicit=None):
    return (explicit or os.environ.get("ANTHROPIC_API_KEY", "")
            or _key_from_dotenv())

PROMPT = """You are writing PDF alt text for a screen-reader user reading a school textbook.

Look at the cropped figure and write ONE concise sentence (max ~25 words) describing what it shows and its instructional point in this context. Rules:
- Do NOT begin with "image of", "picture of", "photo of", or "graphic of".
- Do NOT repeat the caption verbatim; add information a sighted reader gets from the picture.
- Describe only what is visibly present. If labels or numbers are too small to read, describe the figure type without inventing values.
- For a diagram/chart, state what it compares or the relationship it shows.
- If the graphic is purely decorative (a banner, border, icon, background shape, or panel art with no informational content), reply with exactly one word: DECORATIVE

Surrounding page text for context:
\"\"\"{context}\"\"\"

Return only the alt sentence, or DECORATIVE. No preamble."""

CAPTION_PROMPT = """You are writing PDF alt text for a screen-reader user reading a school textbook.

This figure ALREADY has the following printed caption, which the screen reader announces separately:
    "{caption}"

Write ONE concise sentence (max ~25 words) giving the visual information a sighted reader gets from the picture that the caption does NOT already state. Rules:
- Do NOT repeat or paraphrase the caption.
- Do NOT begin with "image of", "picture of", "photo of", or "graphic of".
- Describe only what is visibly present. If labels or numbers are too small to read, describe the figure type without inventing values.
- For a diagram or chart, state what it compares or the relationship it shows.
- This figure is known to be real content, not decoration — always describe it; do not reply DECORATIVE.

Surrounding page text for context:
\"\"\"{context}\"\"\"

Return only the alt sentence. No preamble."""


def _tidy(s: str) -> str:
    s = " ".join(s.strip().split())
    s = re.sub(r'^(an?\s+)?(image|picture|photo|graphic)\s+(of|showing)\s+',
               '', s, flags=re.I)
    if s and s[0].islower():
        s = s[0].upper() + s[1:]
    if s and not s.endswith((".", "!", "?")):
        s += "."
    return s[:250]


def _call_claude_alt(img_png: bytes, prompt_text: str, api_key: str, model: str) -> str:
    """Real vision call. `prompt_text` is the fully-formed instruction (it already
    includes any caption + surrounding context). Reuses the engine's anthropic
    client pattern."""
    if not (_HAS_ANTHROPIC and api_key):
        raise RuntimeError("anthropic SDK or ANTHROPIC_API_KEY not available")
    client = _anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model=model, max_tokens=200,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64",
             "media_type": "image/png",
             "data": base64.b64encode(img_png).decode()}},
            {"type": "text", "text": prompt_text},
        ]}])
    # Record token usage for cost metering (input tokens here include the image).
    try:
        u = getattr(msg, "usage", None)
        _LAST_USAGE["input_tokens"] = int(getattr(u, "input_tokens", 0) or 0)
        _LAST_USAGE["output_tokens"] = int(getattr(u, "output_tokens", 0) or 0)
    except Exception:
        _LAST_USAGE["input_tokens"] = _LAST_USAGE["output_tokens"] = 0
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")


# Substrings that mean "retrying won't help" — auth / credits / bad request.
_NONRETRYABLE = ("credit balance", "authentication", "invalid api key",
                 "invalid x-api-key", "permission", "not found",
                 "401", "403", "404")


def _is_retryable(exc) -> bool:
    """Transient failures (rate limit 429, 5xx, timeouts, dropped connections)
    are worth retrying; auth/credit/bad-request failures are not."""
    msg = str(exc).lower()
    return not any(s in msg for s in _NONRETRYABLE)


def _call_with_retry(vision_fn, png, prompt, api_key, model,
                     attempts=3, base_delay=2.0):
    """Call vision with exponential backoff so a single transient failure does
    not leave a figure un-described (which would strand it on its caption)."""
    last = None
    for i in range(attempts):
        try:
            return vision_fn(png, prompt, api_key, model)
        except Exception as ex:
            last = ex
            if not _is_retryable(ex) or i == attempts - 1:
                raise
            time.sleep(base_delay * (2 ** i))   # 2s, 4s, ...
    raise last  # pragma: no cover


class _BBox:
    """Lightweight stand-in so the suggester can crop an arbitrary rectangle
    (a whole figure's bounds), not just a single MCID's box."""
    __slots__ = ("x0", "y0", "x1", "y1", "valid")

    def __init__(self, x0, y0, x1, y1):
        self.x0, self.y0 = float(x0), float(y0)
        self.x1, self.y1 = float(x1), float(y1)
        self.valid = (self.x1 > self.x0 and self.y1 > self.y0)


def _crop_and_context(doc, pi, bbox, out_png=None):
    """Return (png_bytes, context_text) for a figure at PDF-space bbox."""
    page = doc[pi]
    H = page.rect.height
    # PDF user space (origin bottom-left) -> fitz space (origin top-left)
    clip = fitz.Rect(bbox.x0 - MARGIN, H - bbox.y1 - MARGIN,
                     bbox.x1 + MARGIN, H - bbox.y0 + MARGIN)
    clip = clip & page.rect            # clamp to page
    # Render only as many pixels as the vision model needs. Image cost scales
    # with pixel area, so a full-width figure at a flat 200dpi bills several
    # times what it needs to. Never upscales past DPI.
    _dpi = adaptive_dpi(clip.width, clip.height, base_dpi=DPI)
    pix = page.get_pixmap(dpi=_dpi, clip=clip)
    png = pix.tobytes("png")
    if out_png:
        pix.save(out_png)
    ctx_clip = fitz.Rect(bbox.x0 - CTX_PAD, H - bbox.y1 - CTX_PAD,
                         bbox.x1 + CTX_PAD, H - bbox.y0 + CTX_PAD) & page.rect
    ctx = page.get_text("text", clip=ctx_clip).strip()
    return png, ctx


def suggest(pdf_path, alt_needs_json, decisions_out,
            api_key=None, model=MODEL, vision_fn=None, dump_crops=None):
    api_key = _resolve_key(api_key)
    vision_fn = vision_fn or _call_claude_alt

    with open(alt_needs_json, encoding="utf-8") as fh:
        needs = json.load(fh).get("needs_human", [])

    with pikepdf.open(pdf_path) as pdf:
        boxes = document_mcid_boxes(pdf)

    doc = fitz.open(pdf_path)
    cache = AltCache()
    ledger = SavingsLedger()
    cost = {"input_tokens": 0, "output_tokens": 0, "usd": 0.0, "billed_calls": 0}
    decisions, skipped = [], []
    for e in needs:
        pi, m = e["page"] - 1, e["mcid"]
        bbox = boxes.get((pi, m))
        eb = e.get("bbox")
        if eb and len(eb) == 4:
            fig_box = _BBox(eb[0], eb[1], eb[2], eb[3])
            if fig_box.valid:
                bbox = fig_box          # crop the whole figure, not one MCID
        if bbox is None or not getattr(bbox, "valid", False):
            skipped.append({"page": e["page"], "mcid": m, "why": "no bbox"})
            continue
        crop_path = (os.path.join(dump_crops, f"p{e['page']}_m{m}.png")
                     if dump_crops else None)
        png, ctx = _crop_and_context(doc, pi, bbox, crop_path)
        caption = (e.get("caption") or "").strip()
        known = bool(e.get("known_content"))

        bw, bh = (bbox.x1 - bbox.x0), (bbox.y1 - bbox.y0)

        # ---- (1) decorative pre-filter: no API call -------------------
        # Repeating UI badges ("Think and Discuss" icons, rules, swatches)
        # carry no information a screen reader needs. Marking them Artifact
        # is both cheaper and MORE correct than describing them.
        if DECOR_FILTER_ON:
            is_dec, why = looks_decorative(png, bw, bh, caption, known)
            if is_dec:
                ledger.bump("decorative")
                decisions.append({"page": e["page"], "mcid": m,
                                  "decorative": True,
                                  "source": "heuristic", "why": why,
                                  "verified": False})
                continue

        # ---- (2) caption reuse: no API call ---------------------------
        # If the printed caption already stands alone as a description, use
        # it. See alt_cost_saver for the PDF/UA caveat; disable with
        # ORION_ALT_CAPTION_REUSE=0 to always get a complementary sentence.
        if CAPTION_REUSE_ON and caption and caption_is_sufficient(caption):
            ledger.bump("caption")
            decisions.append({"page": e["page"], "mcid": m,
                              "alt": caption_as_alt(caption),
                              "source": "caption-reuse", "verified": False})
            continue

        if caption:
            prompt_text = CAPTION_PROMPT.format(caption=caption, context=ctx[:1500])
        else:
            prompt_text = PROMPT.format(context=ctx[:1500])

        # ---- (3) cache: no API call on a repeat -----------------------
        # Keyed on image bytes + prompt + model, so re-running the same PDF
        # during debugging is free, and figures repeated across pages are
        # billed once.
        ck = cache.key(png, prompt_text, model)
        cached = cache.get(ck)
        if cached is not None:
            ledger.bump("cache")
            decisions.append({"page": e["page"], "mcid": m, "alt": cached,
                              "source": "cache", "verified": False})
            continue

        try:
            _LAST_USAGE["input_tokens"] = _LAST_USAGE["output_tokens"] = 0
            ans = _call_with_retry(vision_fn, png, prompt_text, api_key, model)
            ledger.bump("llm")
            # Meter cost from the token usage the call just recorded.
            _it, _ot = _LAST_USAGE["input_tokens"], _LAST_USAGE["output_tokens"]
            cost["input_tokens"] += _it
            cost["output_tokens"] += _ot
            cost["usd"] += _usd(_it, _ot)
            cost["billed_calls"] += 1
        except Exception as ex:
            ledger.bump("skipped")
            skipped.append({"page": e["page"], "mcid": m, "why": f"vision: {ex}"})
            continue
        is_dec = ans.strip().upper().startswith("DECORATIVE")
        if is_dec and not known:
            decisions.append({"page": e["page"], "mcid": m,
                              "decorative": True,
                              "source": "vision", "verified": False})
        elif is_dec and known:
            # Known real content the model declined to describe. Never artifact
            # it -- keep the caption we already have as the Alt.
            if caption:
                decisions.append({"page": e["page"], "mcid": m, "alt": caption,
                                  "source": "caption-fallback", "verified": False})
            else:
                skipped.append({"page": e["page"], "mcid": m,
                                "why": "vision DECORATIVE for known content, no caption"})
        else:
            _alt = _tidy(ans)
            cache.put(ck, _alt)          # bill this image at most once, ever
            decisions.append({"page": e["page"], "mcid": m,
                              "alt": _alt,
                              "source": "vision", "verified": False})
    doc.close()

    with open(decisions_out, "w", encoding="utf-8") as fh:
        json.dump(decisions, fh, indent=2, ensure_ascii=False)
    savings = ledger.summary()
    cost["usd"] = round(cost["usd"], 4)
    print(f"[alt] model={model} api_calls={savings['api_calls']} "
          f"avoided={savings['calls_avoided']} ({savings['avoided_pct']}%) "
          f"breakdown={{decorative:{savings['decorative']}, "
          f"caption:{savings['caption']}, cache:{savings['cache']}}} "
          f"cache={cache.stats()} "
          f"cost=${cost['usd']:.4f} "
          f"(in={cost['input_tokens']} out={cost['output_tokens']} tok, "
          f"billed={cost['billed_calls']} calls)", file=sys.stderr)
    return {"decisions": decisions, "skipped": skipped,
            "resolved": len(decisions), "of": len(needs),
            "savings": savings, "cache": cache.stats(), "cost": cost}


def preflight(pdf_path=None, alt_needs_json=None, api_key=None, model=MODEL):
    """One-shot end-to-end check of the vision path BEFORE a full run.
    Verifies, in order: SDK importable -> key present -> a live API call
    succeeds (auth + model access + network). If a pdf + alt_needs is given,
    it crops the first real figure and asks for an actual description so you
    see a genuine result; otherwise it sends a tiny synthetic image.

    Returns {"ok": bool, "stage": str, "detail": str, "sample": str|None}.
    stage is the first thing that failed: 'sdk' | 'key' | 'crop' | 'api' | 'ok'
    """
    api_key = _resolve_key(api_key)
    # 1) SDK
    if not _HAS_ANTHROPIC:
        return {"ok": False, "stage": "sdk", "sample": None,
                "detail": "anthropic SDK not importable in this venv "
                          "(pip install anthropic)"}
    # 2) key
    if not api_key:
        return {"ok": False, "stage": "key", "sample": None,
                "detail": "ANTHROPIC_API_KEY not found in this process OR in "
                          "repo-root/.env (checked both)"}
    # 3) build one image + context
    ctx = "self-test"
    try:
        if pdf_path and alt_needs_json:
            with open(alt_needs_json, encoding="utf-8") as fh:
                needs = json.load(fh).get("needs_human", [])
            if needs:
                with pikepdf.open(pdf_path) as pdf:
                    boxes = document_mcid_boxes(pdf)
                e = needs[0]
                bbox = boxes.get((e["page"] - 1, e["mcid"]))
                doc = fitz.open(pdf_path)
                png, ctx = _crop_and_context(doc, e["page"] - 1, bbox)
                doc.close()
            else:
                png = _tiny_png()
        else:
            png = _tiny_png()
    except Exception as ex:
        return {"ok": False, "stage": "crop", "sample": None,
                "detail": f"figure crop failed: {ex}"}
    # 4) live call
    try:
        ans = _call_claude_alt(png, PROMPT.format(context=ctx), api_key, model)
    except Exception as ex:
        return {"ok": False, "stage": "api", "sample": None,
                "detail": f"live API call failed with model '{model}': {ex}"}
    return {"ok": True, "stage": "ok", "sample": _tidy(ans),
            "detail": f"vision path OK (model '{model}')"}


def _tiny_png():
    # 2x2 grey PNG, no external deps
    import zlib, struct
    raw = b"".join(b"\x00" + bytes([120, 120]) for _ in range(2))
    def chunk(t, d):
        return (struct.pack(">I", len(d)) + t + d
                + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff))
    ihdr = struct.pack(">IIBBBBB", 2, 2, 8, 0, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf", nargs="?")
    ap.add_argument("alt_needs", nargs="?")
    ap.add_argument("decisions_out", nargs="?")
    ap.add_argument("--dump-crops", default=None)
    ap.add_argument("--selftest", action="store_true",
                    help="probe SDK+key+live API (optionally with pdf+alt_needs) and exit")
    a = ap.parse_args()

    if a.selftest:
        r = preflight(a.pdf, a.alt_needs)
        mark = "OK " if r["ok"] else "FAIL"
        print(f"[selftest] {mark} stage={r['stage']}: {r['detail']}")
        if r.get("sample"):
            print(f"[selftest] sample description: {r['sample']!r}")
        sys.exit(0 if r["ok"] else 1)

    if not (a.pdf and a.alt_needs and a.decisions_out):
        ap.error("pdf, alt_needs, and decisions_out are required (or use --selftest)")
    r = suggest(a.pdf, a.alt_needs, a.decisions_out, dump_crops=a.dump_crops)
    print(f"resolved {r['resolved']}/{r['of']} -> {a.decisions_out}")
    if r["skipped"]:
        print("skipped:", r["skipped"])
