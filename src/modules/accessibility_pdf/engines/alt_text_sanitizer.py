#!/usr/bin/env python3
"""
alt_text_sanitizer.py
=====================
Repairs Figure /Alt text.  Runs AFTER reading_order_fixer + heading_eligibility_filter.

The defect this solves
----------------------
Every Figure has an /Alt, so PAC is green.  But in G6_CB_SCIENCE_Ch02 the Alt
values were:

  * PLACEHOLDER  "Figure 1", "Figure 28", "Figure 41" ...   -> WCAG 1.1.1 fail
  * DUMP         the entire body text of the box the figure sits behind, while
                 that same text is ALSO tagged as <P> -> screen reader reads it
                 twice
  * CORRUPT      "DCG *: Explores the living world *nd understands *he ..."
                 the Alt generator wrote '*' wherever a glyph failed to decode.
                 Raw bytes confirm the '*' is really in the file.

None of that is detectable by PAC or veraPDF.  All of it is obvious to a human
opening the tag tree.

What it does
------------
For every Figure whose Alt is placeholder / dump / corrupt / empty:

  1. CAPTION      Look for a short text element (<=60 chars) directly beneath
                  the figure and horizontally overlapping it - that is the
                  printed caption ("Camel from the cold desert of Ladakh").
                  If found: Alt = caption.  Figure stays a Figure.

  2. DECORATIVE   No caption -> the figure is page furniture: the rounded box
                  behind an activity panel, a banner strip, a 44pt icon.  The
                  correct PDF/UA treatment is /Artifact, not a Figure with an
                  invented Alt.  So: the image MCIDs are re-marked /Artifact in
                  the content stream and the Figure element is dropped.

  3. SPLIT        Those decorative boxes have real text trapped inside them -
                  the live "Exploratory Activity 1" banner label, for instance.
                  Text inside a Figure is REPLACED by the Alt for assistive
                  tech, i.e. lost.  So before artifacting, every text MCID is
                  lifted out into a sibling <P> at the same position.  Nothing
                  is lost and nothing is announced twice.

  4. CLEAN        NUL bytes and control characters stripped from every
                  surviving Alt (the Legislative Summary chart Alt ended in
                  \\x00), whitespace collapsed.

Anything the tool cannot derive honestly is NOT invented - it is written to
--report-json as NEEDS_HUMAN with page and size, for a person to caption.

Re-parenting MCIDs invalidates the ParentTree, so it is rebuilt at the end.

Usage
-----
    python alt_text_sanitizer.py in.pdf out.pdf [--report] [--report-json f.json]
"""
from __future__ import annotations

import json
import os
import re
import sys
import unicodedata

import pikepdf
from pikepdf import Dictionary, Name, Array

try:
    from .mcid_geometry import page_mcid_boxes
    from .struct_utils import (rebuild_parent_tree, artifact_mcids,
                               fix_struct_parents, strip_ghost_refs, prune_empty)
except ImportError:
    from mcid_geometry import page_mcid_boxes
    from struct_utils import (rebuild_parent_tree, artifact_mcids,
                              fix_struct_parents, strip_ghost_refs, prune_empty)

# Load repo-root .env into os.environ BEFORE reading ENRICH_CAPTIONED below.
try:
    from .env_bootstrap import load_repo_dotenv
except ImportError:
    from env_bootstrap import load_repo_dotenv
load_repo_dotenv()

RE_PLACEHOLDER = re.compile(r"^(figure|image|graphic|picture|img|pic)\s*[\d\.\-_]*$", re.I)
RE_CORRUPT = re.compile(r"[A-Za-z]\*|\*[A-Za-z]")
DUMP_CHARS = 70            # an Alt longer than this is prose, not a description
PROVISIONAL = "[TO BE DESCRIBED]"   # never ship this - see --report-json NEEDS_HUMAN
CAPTION_MAX = 60
CAPTION_GAP = 30.0         # pt below the figure
CAPTION_OVERLAP = 0.35     # fraction of figure width
CAPTION_TAGS = {"/P", "/Span", "/Caption"}   # a caption is never a heading

# --------------------------------------------------------------------------
# COST CONTROL — vision enrichment of already-captioned figures
# --------------------------------------------------------------------------
# A figure that has a printed caption (or a short "ok" Alt echoing that caption)
# ALREADY has a usable Alt: we set Alt = caption above. Historically we *also*
# queued every such figure for Step 11.5 Claude-vision so the final Alt could
# ADD the visual detail the caption omits. That meant one Haiku vision call per
# captioned figure — the single biggest source of API cost, since most figures
# in a textbook are captioned.
#
# This flag makes that enrichment OPT-IN. Default OFF => vision fires ONLY for
# figures that have NO caption/alt (the "no printed caption" path below); a
# captioned figure simply keeps its caption as the Alt at zero API cost.
#
# To restore the old higher-quality-but-pricier behaviour for a single run,
# set the env var before launching the pipeline:
#     ORION_ALT_ENRICH_CAPTIONED=1
# (accepts 1/true/yes/on, case-insensitive). No code change needed to revert.
ENRICH_CAPTIONED = os.environ.get(
    "ORION_ALT_ENRICH_CAPTIONED", "0").strip().lower() in ("1", "true", "yes", "on")
PHOTO_AREA = 3000.0        # pt^2: bigger than this and it is real imagery, not box art
BOX_WIDTH_FRAC = 0.60      # a figure this wide is a panel/banner, not a picture
BOX_AREA_FRAC = 0.35       # ...or one that covers this much of the page


def clean(s: str) -> str:
    """Strip NULs / control chars, collapse whitespace."""
    if not s:
        return ""
    s = "".join(c for c in s if c == "\n" or unicodedata.category(c)[0] != "C")
    return re.sub(r"\s+", " ", s).strip()


def classify(alt: str):
    a = clean(alt)
    if not a:
        return "empty"
    if RE_PLACEHOLDER.match(a):
        return "placeholder"
    if RE_CORRUPT.search(a) or "\x00" in (alt or ""):
        return "corrupt"
    if len(a) > DUMP_CHARS:
        return "dump"
    return "ok"


def run(inp, outp, report=False, report_json=None):
    pdf = pikepdf.open(inp)
    pages = list(pdf.pages)
    pidx = {p.obj.objgen: i for i, p in enumerate(pages)}

    cache, boxes = {}, {}
    for i, pg in enumerate(pages):
        for m, b in page_mcid_boxes(pg, cache).items():
            boxes[(i, m)] = b

    # ---- inventory ------------------------------------------------------
    figs, texts = [], []

    def leaves(n, cur, out):
        if isinstance(n, Array):
            for k in n:
                leaves(k, cur, out)
            return
        if isinstance(n, int):
            if cur is not None:
                out.append((cur, int(n)))
            return
        if not isinstance(n, Dictionary):
            return
        if n.get("/Type") == Name("/MCR"):
            pg = n.get("/Pg")
            pi = pidx.get(pg.objgen) if pg is not None else cur
            if pi is not None:
                out.append((pi, int(n.get("/MCID"))))
            return
        if n.get("/Type") == Name("/OBJR"):
            return
        pg = n.get("/Pg")
        nx = pidx.get(pg.objgen) if pg is not None else cur
        leaves(n.get("/K"), nx, out)

    def walk(n, cur, parent):
        if isinstance(n, Array):
            for k in n:
                walk(k, cur, parent)
            return
        if not isinstance(n, Dictionary):
            return
        if n.get("/Type") in (Name("/MCR"), Name("/OBJR")):
            return
        pg = n.get("/Pg")
        c = pidx.get(pg.objgen) if pg is not None else cur
        s = n.get("/S")
        if s is not None:
            lv = []
            leaves(n, c, lv)
            bl = [boxes[k] for k in lv if k in boxes and boxes[k].valid]
            if bl:
                rec = {
                    "node": n, "parent": parent, "tag": str(s), "page": lv[0][0],
                    "img": [k for k in lv if k in boxes and boxes[k].valid
                            and boxes[k].is_image],
                    "vec": [k for k in lv if k in boxes and boxes[k].valid
                            and not boxes[k].is_image and not boxes[k].text.strip()],
                    "txt": [k for k in lv if k in boxes and boxes[k].chars > 0],
                    "text": "".join(boxes[k].text for k in lv if k in boxes).strip(),
                    "x0": min(b.x0 for b in bl), "x1": max(b.x1 for b in bl),
                    "y0": min(b.y0 for b in bl), "y1": max(b.y1 for b in bl),
                }
                (figs if str(s) == "/Figure" else texts).append(rec)
        walk(n.get("/K"), c, n)

    walk(pdf.Root["/StructTreeRoot"].get("/K"), None, None)

    def is_boxlike(f):
        mb = pages[f["page"]].mediabox
        pw = float(mb[2]) - float(mb[0])
        ph = float(mb[3]) - float(mb[1])
        w, h = f["x1"] - f["x0"], f["y1"] - f["y0"]
        # a panel spans the text column, or eats a big share of the page
        return w > BOX_WIDTH_FRAC * pw or (w * h) > BOX_AREA_FRAC * pw * ph

    def caption_for(f):
        if is_boxlike(f):
            return None
        w, h = f["x1"] - f["x0"], f["y1"] - f["y0"]
        pictureish = bool(f["img"]) or (w >= 100 and h >= 60)
        if not pictureish:
            return None          # a 47x40 icon does not get the caption below it
        best = None
        w = f["x1"] - f["x0"]
        for t in texts:
            if t["page"] != f["page"] or t["tag"] not in CAPTION_TAGS:
                continue
            tx = clean(t["text"])
            if not (3 <= len(tx) <= CAPTION_MAX):
                continue
            if tx.endswith(("?", ":", ";")) or tx[0] in "•-–":
                continue          # a question or a run-in label is not a caption
            if min(f["x1"], t["x1"]) - max(f["x0"], t["x0"]) < CAPTION_OVERLAP * w:
                continue
            gap = f["y0"] - t["y1"]
            if -4 <= gap <= CAPTION_GAP and (best is None or gap < best[0]):
                best = (gap, tx)
        return best[1] if best else None

    def _is_real_picture(f):
        """A figure carrying genuine imagery (a photo or a large drawing),
        as opposed to a banner strip or a tiny icon."""
        if is_boxlike(f):
            return False
        w, h = f["x1"] - f["x0"], f["y1"] - f["y0"]
        return bool(f["img"]) or (w >= 100 and h >= 60)

    def _enrich_mcid(f):
        """Representative MCID for cropping / for alt_apply to locate the figure:
        the largest photo-area image, else the largest leaf box of any kind."""
        cand = []
        for _, m in f["img"]:
            b = boxes.get((f["page"], m))
            if b:
                cand.append(((b.x1 - b.x0) * (b.y1 - b.y0), m))
        if not cand:
            for _, m in (f["img"] + f["vec"] + f["txt"]):
                b = boxes.get((f["page"], m))
                if b:
                    cand.append(((b.x1 - b.x0) * (b.y1 - b.y0), m))
        return max(cand)[1] if cand else None

    def _queue_enrich(f, caption_text, was, known=True):
        """Queue a captioned figure for Step 11.5 (vision) so the final Alt
        ADDS what the caption omits. The caption we already wrote stays as a
        graceful fallback if vision can't run (no key / no credits / offline).
        known=True: a geometrically-confirmed picture+caption -> never artifact.
        known=False: a short-alt guess -> vision may still rule it DECORATIVE
        (banner/icon chrome) so it gets artifacted instead of described.

        COST GATE: by default (ENRICH_CAPTIONED=False) this is a no-op — the
        figure keeps the caption we already wrote as its Alt and NO vision call
        is spent on it. Only figures with no caption/alt reach Step 11.5. Set
        ORION_ALT_ENRICH_CAPTIONED=1 to re-enable per-figure enrichment."""
        if not ENRICH_CAPTIONED:
            return
        m = _enrich_mcid(f)
        if m is None:
            return
        log["needs_human"].append({
            "page": f["page"] + 1, "mcid": m,
            "caption": clean(caption_text)[:CAPTION_MAX],
            "known_content": known,
            "bbox": [round(f["x0"], 1), round(f["y0"], 1),
                     round(f["x1"], 1), round(f["y1"], 1)],
            "was": was,
            "reason": "figure has a caption/short alt — vision should add what the caption omits",
        })

    # ---- repair ---------------------------------------------------------
    log = {"captioned": [], "artifacted": [], "split": [], "cleaned": [], "needs_human": []}
    to_artifact = {}      # page_index -> set(mcid)

    for f in figs:
        node, parent = f["node"], f["parent"]
        alt_raw = str(node.get("/Alt")) if node.get("/Alt") is not None else ""
        kind = classify(alt_raw)
        page = f["page"]
        txt_mcids = [m for _, m in f["txt"]]
        img_mcids = [m for _, m in f["img"]]
        vec_mcids = [m for _, m in f["vec"]]

        if kind == "ok":
            c = clean(alt_raw)
            if c != alt_raw:
                node["/Alt"] = pikepdf.String(c)
                log["cleaned"].append({"page": page + 1, "alt": c})
            if txt_mcids:                      # real text swallowed by a good Alt
                _split_text_out(pdf, pages, node, parent, txt_mcids, page)
                log["split"].append({"page": page + 1, "mcids": txt_mcids,
                                     "keep_alt": clean(alt_raw)})
            # A short "ok" Alt on a real picture is almost always the caption
            # echoed back ("Herbs", "Tap roots", "Camel from the hot desert of
            # Rajasthan"), not a description. Send it to vision to be enriched;
            # the current Alt remains the fallback.
            if _is_real_picture(f) and len(c) <= CAPTION_MAX:
                _queue_enrich(f, c, "ok", known=False)
            continue

        cap = caption_for(f)
        if cap:
            node["/Alt"] = pikepdf.String(cap)
            log["captioned"].append({"page": page + 1, "was": kind,
                                     "old": clean(alt_raw)[:60], "new": cap})
            if txt_mcids:
                _split_text_out(pdf, pages, node, parent, txt_mcids, page)
                log["split"].append({"page": page + 1, "mcids": txt_mcids})
            # The caption names the figure; it does not describe it. Queue the
            # figure for vision so the final Alt adds the visual detail the
            # caption omits. The caption stays as the fallback.
            _queue_enrich(f, cap, kind)
            continue

        # no caption -> decorative page furniture.
        # But a panel can BUNDLE real photos with its box art (p2 holds the
        # camel/lotus/frog/tiger images).  Artifacting those would delete
        # meaningful content, so rescue anything photo-sized first.
        photos, furniture = [], []
        for m in img_mcids:
            b = boxes[(page, m)]
            area = (b.x1 - b.x0) * (b.y1 - b.y0)
            (photos if area >= PHOTO_AREA else furniture).append(m)
        furniture += [m for _, m in f["vec"]]      # box frames, rules, banners

        if txt_mcids:
            _split_text_out(pdf, pages, node, parent, txt_mcids, page)
            log["split"].append({"page": page + 1, "mcids": txt_mcids,
                                 "note": "lifted out of decorative figure"})

        for m in photos:
            b = boxes[(page, m)]
            fig = pdf.make_indirect(Dictionary(
                Type=Name("/StructElem"), S=Name("/Figure"), Pg=pages[page].obj,
                P=parent, K=Array([m]),
                Alt=pikepdf.String(PROVISIONAL)))
            _insert_before(parent, node, fig)
            log["needs_human"].append({
                "page": page + 1, "mcid": m,
                "size": [round(b.x1 - b.x0), round(b.y1 - b.y0)],
                "reason": "photo with no printed caption - needs a written description",
            })

        _detach(node, parent)
        leftover = set(_k_mcids(node, page, pidx)) - set(txt_mcids) - set(photos)
        to_artifact.setdefault(page, set()).update(furniture)
        to_artifact[page].update(leftover)
        log["artifacted"].append({
            "page": page + 1, "was": kind, "old": clean(alt_raw)[:60],
            "size": [round(f["x1"] - f["x0"]), round(f["y1"] - f["y0"])],
            "images": len(furniture), "photos_rescued": len(photos),
        })

    # ---- content-stream artifacting -------------------------------------
    n_art = 0
    for pi, mcids in to_artifact.items():
        n_art += artifact_mcids(pdf, pages[pi], mcids)

    strip_ghost_refs(pdf)
    prune_empty(pdf)
    fix_struct_parents(pdf)
    rebuild_parent_tree(pdf)
    pdf.save(outp)
    pdf.close()   # Windows: os.replace() is denied while the file is still open

    if report:
        print(f"figures examined   : {len(figs)}")
        print(f"Alt from caption   : {len(log['captioned'])}")
        for c in log["captioned"]:
            print(f"    p{c['page']:<3} {c['was']:<11} {c['old']!r}\n            -> {c['new']!r}")
        print(f"decorative -> Artifact : {len(log['artifacted'])} figures, {n_art} MC re-marked")
        for a in log["artifacted"]:
            print(f"    p{a['page']:<3} {a['was']:<11} {a['size'][0]}x{a['size'][1]}  was {a['old']!r}")
        print(f"text lifted out of figures : {len(log['split'])} elements")
        print(f"Alt strings cleaned        : {len(log['cleaned'])}")
        print(f"NEEDS_HUMAN                : {len(log['needs_human'])}")
    if report_json:
        with open(report_json, "w", encoding="utf-8") as fh:
            json.dump(log, fh, indent=2)
    print(f"saved {outp}")


def _k_mcids(node, page, pidx):
    """Every MCID still hanging off this element's /K (bbox or not)."""
    k = node.get("/K")
    items = list(k) if isinstance(k, Array) else ([k] if k is not None else [])
    out = []
    for it in items:
        if isinstance(it, int):
            out.append(int(it))
        elif isinstance(it, Dictionary) and it.get("/Type") == Name("/MCR"):
            out.append(int(it["/MCID"]))
    return out


def _insert_before(parent, anchor, new):
    k = parent.get("/K")
    if not isinstance(k, Array):
        return
    out = []
    for c in k:
        if isinstance(c, Dictionary) and c.objgen == anchor.objgen:
            out.append(new)
        out.append(c)
    parent["/K"] = Array(out)


def _detach(node, parent):
    """
    Remove `node` from parent's /K, but HOIST any struct-element children it
    still owns up into its slot. Dropping them would orphan their marked
    content (PAC: content with no struct parent).
    """
    if parent is None:
        return
    k = parent.get("/K")
    if not isinstance(k, Array):
        return
    nk = node.get("/K")
    kids = list(nk) if isinstance(nk, Array) else ([nk] if nk is not None else [])
    survivors = [c for c in kids
                 if isinstance(c, Dictionary) and c.get("/S") is not None]
    out = []
    for c in k:
        if isinstance(c, Dictionary) and c.objgen == node.objgen:
            for sv in survivors:
                sv["/P"] = parent
                out.append(sv)
        else:
            out.append(c)
    parent["/K"] = Array(out)


def _split_text_out(pdf, pages, fig, parent, txt_mcids, page, replace=False):
    """
    Move text MCIDs out of a Figure into a sibling <P> placed at the Figure's
    slot.  Text inside a Figure is replaced by the Alt for assistive tech, so
    leaving it there means losing it.
    """
    if parent is None:
        return
    keep = set(txt_mcids)
    fk = fig.get("/K")
    items = list(fk) if isinstance(fk, Array) else ([fk] if fk is not None else [])

    moved, stay = [], []
    for it in items:
        m = int(it) if isinstance(it, int) else (
            int(it["/MCID"]) if isinstance(it, Dictionary) and it.get("/Type") == Name("/MCR")
            else None)
        (moved if m in keep else stay).append(it)
    if not moved:
        return

    para = pdf.make_indirect(Dictionary(
        Type=Name("/StructElem"), S=Name("/P"),
        Pg=pages[page].obj, P=parent, K=Array(moved)))
    fig["/K"] = Array(stay)

    k = parent.get("/K")
    if isinstance(k, Array):
        out = []
        for c in k:
            if isinstance(c, Dictionary) and c.objgen == fig.objgen:
                out.append(para)
                if not replace:
                    out.append(c)
            else:
                out.append(c)
        parent["/K"] = Array(out)


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    rj = None
    if "--report-json" in sys.argv:
        rj = sys.argv[sys.argv.index("--report-json") + 1]
        a = [x for x in a if x != rj]
    run(a[0], a[1], report="--report" in sys.argv, report_json=rj)
