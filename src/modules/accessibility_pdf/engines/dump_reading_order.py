"""
dump_reading_order.py  —  Orion PDF accessibility pipeline diagnostic

Walks StructTreeRoot/K depth-first (screen-reader reading order) and prints
each marked-content leaf with its text + the Y coordinate of its first glyph.
That lets you SEE where reading_order_fixer collapsed the order and whether
the collapse correlates with Y (coordinate-convention bug).

Usage:
    python dump_reading_order.py remediated_G6_CB_SCIENCE_Ch02__1_.pdf
    python dump_reading_order.py file.pdf --page 1        # only page index 1 (0-based)
    python dump_reading_order.py file.pdf > order.txt

Requires: pikepdf, pdfplumber
"""
import sys
import argparse
import pikepdf
import pdfplumber

# Windows consoles default to cp1252 and crash on PUA glyphs (\uf0fc checkmarks,
# subset-font codes). Force UTF-8 with replacement so a dump never dies on text.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def build_page_index(pdf):
    """Map each page's (objgen) -> 0-based page number."""
    idx = {}
    for i, page in enumerate(pdf.pages):
        try:
            idx[page.obj.objgen] = i
        except Exception:
            idx[id(page.obj)] = i
    return idx


def build_mcid_text(pdf_path):
    """
    {page_no: {mcid: {'text': str, 'y0': float, 'tag': str}}}
    y0 is pdfplumber top-origin (0 = top of page); we convert to bottom-origin
    for interpretation. pdfplumber exposes char['mcid'] and char['tag'].
    """
    out = {}
    with pdfplumber.open(pdf_path) as doc:
        for pno, page in enumerate(doc.pages):
            h = page.height
            m = {}
            for ch in page.chars:
                mcid = ch.get("mcid")
                if mcid is None:
                    continue
                rec = m.setdefault(mcid, {"text": [], "y_top": ch["top"],
                                          "tag": ch.get("tag")})
                rec["text"].append(ch["text"])
                rec["y_top"] = min(rec["y_top"], ch["top"])
            # finalize: join text, convert y to bottom-left origin
            for mcid, rec in m.items():
                rec["text"] = "".join(rec["text"])
                rec["y_bl"] = h - rec["y_top"]      # bottom-left Y (PDF user space)
            out[pno] = m
    return out


def resolve_pg_index(elem, inherited_pg, page_index):
    pg = elem.get("/Pg", inherited_pg)
    if pg is None:
        return None, inherited_pg
    try:
        return page_index.get(pg.objgen), pg
    except Exception:
        return None, pg


def walk(node, depth, inherited_pg, page_index, mcid_text, out):
    """Depth-first walk emitting (depth, tag, page, mcid, text, y_bl)."""
    if isinstance(node, pikepdf.Array):
        for child in node:
            walk(child, depth, inherited_pg, page_index, mcid_text, out)
        return

    if isinstance(node, pikepdf.Dictionary):
        typ = node.get("/Type")
        # Marked-content reference dict: /Type /MCR, has /MCID (+ maybe /Pg)
        if typ == pikepdf.Name("/MCR"):
            pno, _ = resolve_pg_index(node, inherited_pg, page_index)
            mcid = int(node.get("/MCID", -1))
            emit_leaf(depth, "(MCR)", pno, mcid, mcid_text, out)
            return
        # Object reference (link/annotation) — no text
        if typ == pikepdf.Name("/OBJR"):
            out.append((depth, "OBJR", None, None, "<annotation/link>", None))
            return
        # Structure element
        tag = str(node.get("/S", "?")).lstrip("/")
        pno, pg = resolve_pg_index(node, inherited_pg, page_index)
        kids = node.get("/K")
        if kids is None:
            out.append((depth, tag, pno, None, "", None))
            return
        out.append((depth, tag, pno, None, "", None))  # container line
        walk(kids, depth + 1, pg, page_index, mcid_text, out)
        return

    # Bare integer => MCID on the inherited page
    try:
        mcid = int(node)
        pno = page_index.get(inherited_pg.objgen) if inherited_pg is not None else None
        emit_leaf(depth, "(int MCID)", pno, mcid, mcid_text, out)
    except Exception:
        out.append((depth, "?", None, None, f"<{type(node).__name__}>", None))


def emit_leaf(depth, kind, pno, mcid, mcid_text, out):
    rec = mcid_text.get(pno, {}).get(mcid) if pno is not None else None
    text = rec["text"] if rec else ""
    y_bl = rec["y_bl"] if rec else None
    out.append((depth, kind, pno, mcid, text, y_bl))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--page", type=int, default=None,
                    help="restrict output to this 0-based page index")
    ap.add_argument("--snippet", type=int, default=70)
    args = ap.parse_args()

    mcid_text = build_mcid_text(args.pdf)
    pdf = pikepdf.open(args.pdf)
    page_index = build_page_index(pdf)

    root = pdf.Root.get("/StructTreeRoot")
    if root is None:
        print("!! No StructTreeRoot — document is not tagged.")
        return
    k = root.get("/K")
    if k is None:
        print("!! StructTreeRoot has no /K.")
        return

    out = []
    walk(k, 0, None, page_index, mcid_text, out)

    print(f"{'ord':>4}  {'pg':>3}  {'y_bl':>7}  tag / text")
    print("-" * 78)
    seq = 0
    prev_y = {}
    for depth, tag, pno, mcid, text, y_bl in out:
        if args.page is not None and pno != args.page:
            continue
        indent = "  " * depth
        snippet = text.strip().replace("\n", " ")[:args.snippet]
        y_str = f"{y_bl:7.1f}" if y_bl is not None else "   --  "
        # Flag a reading-order inversion: Y increasing while walking forward
        # (in correct order Y should generally DECREASE down the page)
        flag = ""
        if y_bl is not None and pno is not None:
            if pno in prev_y and y_bl > prev_y[pno] + 5:
                flag = "  <== Y JUMP UP (possible order inversion)"
            prev_y[pno] = y_bl
        line = f"{seq:>4}  {str(pno):>3}  {y_str}  {indent}{tag}"
        if snippet:
            line += f'  "{snippet}"'
        print(line + flag)
        seq += 1


if __name__ == "__main__":
    main()
