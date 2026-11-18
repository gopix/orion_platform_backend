#!/usr/bin/env python3
"""
accessibility_linter.py
=======================
A *semantic* QA pass for remediated PDFs — the "spell-checker" layer.

Structural checkers (PAC, veraPDF) verify that an Alt attribute EXISTS and that
heading nesting is legal. They cannot tell that an Alt says "h C a p t e r 2" or
"*8", that a heading is really a body sentence, or that text is mojibake. This
module catches that class: content that is structurally valid but semantically
junk.

DESIGN
------
* REPORT-ONLY. This module never mutates the PDF. It walks the structure tree,
  runs a set of deterministic detectors, and emits a JSON + HTML report. Auto-
  fixing the provably-safe findings is a deliberate SECOND phase, kept separate
  so the detectors can be validated first.
* GENERIC. No document-specific strings or page numbers — every detector is a
  rule that applies to any PDF.
* Each finding is tagged ``autofixable`` so a later autofix pass knows which are
  safe to repair without human review.

USAGE
-----
    python accessibility_linter.py <in.pdf> [report.json] [report.html]

Programmatic:
    from accessibility_linter import lint, write_reports
    res = lint("in.pdf")
    write_reports(res, "report.json", "report.html")
"""
from __future__ import annotations

import html
import json
import re
import sys
from collections import Counter
from pathlib import Path

import pikepdf
import fitz  # PyMuPDF — ToUnicode-correct text for spelling/mojibake checks

# Reuse the heading normalizer's content scanner so element text is derived the
# same way the rest of the engine derives it (MCID -> rendered text).
try:
    from .heading_normalizer import _scan_pages, _iter_mcids, _page_index
except ImportError:  # running as a script
    from heading_normalizer import _scan_pages, _iter_mcids, _page_index

# Optional spell check. Absent -> spelling detector silently disabled.
try:
    from spellchecker import SpellChecker  # pyspellchecker
    _HAS_SPELL = True
except Exception:
    SpellChecker = None
    _HAS_SPELL = False


# ---------------------------------------------------------------- severities --
ERROR = "error"        # structurally valid but definitely wrong for a reader
WARNING = "warning"    # very likely wrong; human should confirm
INFO = "info"          # advisory (e.g. possible spelling)

_HEAD = re.compile(r"^/H[1-6]$")

# A bare figure label / number that carries no description.
_BARE_LABEL = re.compile(
    r"^\W*(fig(ure)?|image|graphic|picture|img|pic|table|photo)?\.?\s*\d*\W*$", re.I)
_PLACEHOLDER = re.compile(r"to\s*be\s*described|placeholder|todo|xxx|tbd", re.I)

# Domain / proper-noun allowlist so the (advisory) spell check does not drown in
# legitimate textbook vocabulary. Lowercased. Extend freely — this only
# suppresses INFO-level noise, never errors.
_SPELL_ALLOW = {
    "monocot", "monocots", "dicot", "dicots", "cotyledon", "cotyledons",
    "taxonomy", "biodiversity", "photosynthesis", "chlorophyll", "habitat",
    "habitats", "aquatic", "amphibian", "terrestrial", "organism", "organisms",
    "neem", "peepal", "tulsi", "banyan", "mango", "lotus", "fibrous", "venation",
    "chickpea", "chickpeas", "maize", "shrub", "shrubs", "climber", "climbers",
    "creeper", "creepers", "linnaeus", "carolus", "rajasthan", "ladakh",
    "colour", "colours", "behaviour", "organise", "organised", "honoured",
}
# Spell check is advisory only; disable entirely with this if it is too noisy.
_SPELL_MAX_PER_PAGE = 8


# ---------------------------------------------------------------- text tests --
def _alpha_tokens(s: str):
    return [w for w in re.split(r"\s+", s) if any(c.isalpha() for c in w)]


def is_char_spaced(s: str) -> bool:
    """Char-spaced OCR/extraction junk, e.g. 'h C a p t e r 2', 'P l a n t s'."""
    w = _alpha_tokens(s)
    if len(w) < 4:
        return False
    singles = sum(1 for x in w if len(x) == 1)
    return singles / len(w) >= 0.5


def is_too_short(s: str) -> bool:
    """Essentially no words: single glyph, punctuation, '*8', 'A.'."""
    return len(re.sub(r"[^A-Za-z]", "", s)) <= 2


def is_bare_label(s: str) -> bool:
    return bool(_BARE_LABEL.match(s.strip()))


def is_placeholder(s: str) -> bool:
    return bool(_PLACEHOLDER.search(s))


def is_mojibake(s: str) -> bool:
    """UTF-8 mis-decoded as cp1252/latin-1 (e.g. 'Ã©' for 'é')."""
    for enc in ("cp1252", "latin-1"):
        try:
            fixed = s.encode(enc).decode("utf-8")
            if fixed != s and "�" not in fixed:
                return True
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
    return False


def looks_like_body(s: str) -> bool:
    """A 'heading' that is actually a sentence / paragraph of body copy."""
    return s.count(". ") >= 2 or len(s.split()) > 20


def looks_like_list_item(s: str) -> bool:
    """'1. Plants', '2) Animals' promoted to a heading instead of a list item."""
    return bool(re.match(r"^\s*\(?\d+[.\)]\s+\S", s))


# ---------------------------------------------------------------- core walk ---
def _elem_text(pdf, elem, scan) -> str:
    pi = _page_index(pdf, elem.get("/Pg"))
    parts = []
    for m in _iter_mcids(elem.get("/K")):
        d = scan.get((pi, m))
        if d and d.get("text"):
            parts.append(d["text"])
    return " ".join(parts).strip()


def _stype(elem) -> str:
    try:
        s = elem.get("/S")
        return str(s) if s is not None else ""
    except Exception:
        return ""


def _page_of(pdf, elem):
    pi = _page_index(pdf, elem.get("/Pg"))
    return (pi + 1) if pi is not None else None


def lint(pdf_path: str, spell: bool = True) -> dict:
    """Scan a PDF and return {'findings': [...], 'summary': {...}}."""
    findings: list[dict] = []
    pdf = pikepdf.open(pdf_path)
    st = pdf.Root.get("/StructTreeRoot")
    if st is None:
        return {"findings": [], "summary": {"error": "no StructTreeRoot"},
                "file": Path(pdf_path).name}

    scan = _scan_pages(pdf)

    sp = None
    if spell and _HAS_SPELL:
        sp = SpellChecker()

    seen = set()

    def add(page, category, severity, tag, text, message, suggestion, autofix):
        findings.append({
            "page": page, "category": category, "severity": severity,
            "tag": tag, "text": (text or "")[:160], "message": message,
            "suggestion": suggestion, "autofixable": autofix,
        })

    def check_figure_alt(elem):
        alt = elem.get("/Alt")
        page = _page_of(pdf, elem)
        if alt is None:
            add(page, "alt", ERROR, "Figure", "",
                "Figure has no Alt attribute",
                "Write a concise description, or mark the figure an artifact if "
                "decorative.", False)
            return
        a = str(alt).strip()
        if not a:
            add(page, "alt", ERROR, "Figure", a, "Figure Alt is empty",
                "Add a description or artifact the figure.", False)
        elif is_placeholder(a):
            add(page, "alt", ERROR, "Figure", a,
                "Alt is an unfilled placeholder", "Replace with a real "
                "description (vision or human).", False)
        elif is_char_spaced(a):
            add(page, "alt", ERROR, "Figure", a,
                "Alt is char-spaced/garbled (e.g. 'h C a p t e r 2')",
                "This is decorative title art — artifact it, or set proper text.",
                True)
        elif is_mojibake(a):
            add(page, "alt", ERROR, "Figure", a,
                "Alt contains mojibake (mis-decoded encoding)",
                "Repair encoding (cp1252/latin-1 -> UTF-8).", True)
        elif is_too_short(a) or is_bare_label(a):
            add(page, "alt", WARNING, "Figure", a,
                "Alt is a bare label/too short (e.g. '*8', 'Figure 3')",
                "Describe what the figure shows, or artifact if decorative.",
                False)

    def check_heading(elem, text):
        page = _page_of(pdf, elem)
        if not text:
            return
        if looks_like_list_item(text):
            add(page, "heading", WARNING, _stype(elem), text,
                "Heading looks like a numbered list item",
                "Retag as a list (L/LI/Lbl/LBody) instead of a heading.", False)
        elif looks_like_body(text):
            add(page, "heading", WARNING, _stype(elem), text,
                "Heading looks like body copy (a full sentence/paragraph)",
                "Demote to <P>; a heading should be a short label.", False)

    def walk(node):
        for c in (list(node.get("/K")) if isinstance(node.get("/K"), pikepdf.Array)
                  else [node.get("/K")]):
            if not isinstance(c, pikepdf.Dictionary) or "/S" not in c:
                continue
            key = c.objgen if c.is_indirect else id(c)
            if key in seen:
                continue
            seen.add(key)
            s = _stype(c)
            if s == "/Figure":
                check_figure_alt(c)
            elif _HEAD.match(s):
                check_heading(c, _elem_text(pdf, c, scan))
            walk(c)

    walk(st)

    # ---- page-level text quality (ToUnicode-correct) ----------------------
    # Spelling and mojibake are checked on PyMuPDF's ToUnicode-decoded page text,
    # NOT the heading scanner's raw-byte text: the latter decodes font bytes as
    # latin-1 and silently drops ligature glyphs (ff/fi/fl), which would flag
    # "flowers"->"owers", "different"->"erent" as false misspellings.
    try:
        doc = fitz.open(pdf_path)
    except Exception:
        doc = None
    if doc is not None:
        for pi in range(len(doc)):
            ptext = doc[pi].get_text("text")
            if not ptext:
                continue
            if is_mojibake(ptext):
                add(pi + 1, "text", ERROR, "/P", ptext[:120],
                    "Page text contains mojibake (mis-decoded encoding)",
                    "Repair encoding (cp1252/latin-1 -> UTF-8).", True)
            if sp is not None:
                words = re.findall(r"[A-Za-z]{4,}", ptext)
                cand = [w for w in words
                        if w.islower() and w not in _SPELL_ALLOW]
                wrong = sorted(set(sp.unknown(cand)))[:_SPELL_MAX_PER_PAGE] \
                    if cand else []
                if wrong:
                    add(pi + 1, "spelling", INFO, "/P", "",
                        "Possible spelling issue(s): " + ", ".join(wrong),
                        "Review flagged words (may be domain terms/OCR).", False)
        doc.close()

    by_sev = Counter(f["severity"] for f in findings)
    by_cat = Counter(f["category"] for f in findings)
    summary = {
        "errors": by_sev.get(ERROR, 0),
        "warnings": by_sev.get(WARNING, 0),
        "info": by_sev.get(INFO, 0),
        "by_category": dict(by_cat),
        "autofixable": sum(1 for f in findings if f["autofixable"]),
        "spell_enabled": sp is not None,
    }
    return {"findings": findings, "summary": summary,
            "file": Path(pdf_path).name}


# ---------------------------------------------------------------- reporting ---
def write_reports(res: dict, json_path: str | None = None,
                  html_path: str | None = None) -> None:
    if json_path:
        Path(json_path).write_text(json.dumps(res, indent=2, ensure_ascii=False),
                                   encoding="utf-8")
    if html_path:
        Path(html_path).write_text(_render_html(res), encoding="utf-8")


_SEV_COLOR = {ERROR: "#c0392b", WARNING: "#d68910", INFO: "#2471a3"}


def _render_html(res: dict) -> str:
    s = res.get("summary", {})
    rows = sorted(res.get("findings", []),
                  key=lambda f: (f["page"] or 0,
                                 {ERROR: 0, WARNING: 1, INFO: 2}[f["severity"]]))
    trs = []
    for f in rows:
        color = _SEV_COLOR.get(f["severity"], "#333")
        trs.append(
            f"<tr>"
            f"<td style='text-align:center'>{f['page'] if f['page'] else '-'}</td>"
            f"<td style='color:{color};font-weight:600'>{html.escape(f['severity'])}</td>"
            f"<td>{html.escape(f['category'])}</td>"
            f"<td><code>{html.escape(f['tag'])}</code></td>"
            f"<td>{html.escape(f['text']) or '<em>(none)</em>'}</td>"
            f"<td>{html.escape(f['message'])}</td>"
            f"<td>{html.escape(f['suggestion'])}</td>"
            f"<td style='text-align:center'>{'✓' if f['autofixable'] else ''}</td>"
            f"</tr>")
    body = "\n".join(trs) or "<tr><td colspan='8'>No findings 🎉</td></tr>"
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>Accessibility QA — {html.escape(res.get('file',''))}</title>
<style>
body{{font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;margin:24px;color:#222}}
h1{{font-size:20px;margin:0 0 4px}}
.sub{{color:#666;margin-bottom:16px}}
.badges span{{display:inline-block;padding:3px 10px;border-radius:12px;margin-right:8px;color:#fff;font-weight:600}}
table{{border-collapse:collapse;width:100%;font-size:13px}}
th,td{{border:1px solid #ddd;padding:6px 8px;vertical-align:top;text-align:left}}
th{{background:#f5f5f5}}
code{{background:#f0f0f0;padding:1px 4px;border-radius:3px}}
</style></head><body>
<h1>Accessibility QA linter — {html.escape(res.get('file',''))}</h1>
<div class="sub">Semantic checks that PAC/veraPDF cannot see. Report-only; no changes were made to the PDF.</div>
<div class="badges">
<span style="background:{_SEV_COLOR[ERROR]}">{s.get('errors',0)} errors</span>
<span style="background:{_SEV_COLOR[WARNING]}">{s.get('warnings',0)} warnings</span>
<span style="background:{_SEV_COLOR[INFO]}">{s.get('info',0)} info</span>
<span style="background:#555">{s.get('autofixable',0)} auto-fixable</span>
</div>
<p style="color:#666">Categories: {html.escape(json.dumps(s.get('by_category',{})))} &middot; spell-check: {'on' if s.get('spell_enabled') else 'off (install pyspellchecker)'}</p>
<table>
<thead><tr><th>Page</th><th>Severity</th><th>Category</th><th>Tag</th><th>Text</th><th>Issue</th><th>Suggested fix</th><th>Auto</th></tr></thead>
<tbody>
{body}
</tbody></table></body></html>"""


def main(argv):
    if len(argv) < 2:
        print("Usage: accessibility_linter.py <in.pdf> [report.json] [report.html]",
              file=sys.stderr)
        return 2
    pdf_path = argv[1]
    stem = str(Path(pdf_path).with_suffix(""))
    json_path = argv[2] if len(argv) > 2 else stem + "_qa.json"
    html_path = argv[3] if len(argv) > 3 else stem + "_qa.html"
    res = lint(pdf_path)
    write_reports(res, json_path, html_path)
    s = res["summary"]
    print(json.dumps({"file": res["file"], **s,
                      "json": json_path, "html": html_path}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
