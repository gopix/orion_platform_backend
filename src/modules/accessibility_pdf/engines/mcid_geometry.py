#!/usr/bin/env python3
"""
mcid_geometry.py
----------------
Shared helper: builds a {(page_index, mcid): BBox} map by walking every page's
content stream.  Used by reading_order_fixer.py and heading_eligibility_filter.py.

Why not PyMuPDF: MuPDF does not expose MCIDs.  We need the marked-content id ->
position link, so the content stream has to be walked directly.

Notes on correctness (these bit us before):
  * Td/TD are RELATIVE to the current text line matrix, not absolute.
  * TD also sets the leading (TL = -ty).  T* / ' / " use TL.  Hardcoding TL=12
    makes every T*-driven line drift, which silently corrupts every y value.
  * Text render matrix = Tm x CTM.  The q/Q stack must be tracked for CTM.
  * Form XObjects carry their own /Matrix and /Resources; recurse into them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import pikepdf
from pikepdf import Dictionary, Name, Array


@dataclass
class BBox:
    x0: float = 1e9
    y0: float = 1e9
    x1: float = -1e9
    y1: float = -1e9
    chars: int = 0
    text: str = ""
    is_image: bool = False      # True only if an image XObject was drawn in this MC
    sizes: list = field(default_factory=list)
    fonts: list = field(default_factory=list)

    def add(self, x, y, size, char_count):
        self.x0 = min(self.x0, x)
        self.x1 = max(self.x1, x + max(size, 1) * 0.5 * char_count)
        self.y0 = min(self.y0, y)
        self.y1 = max(self.y1, y + max(size, 1))

    def add_rect(self, x0, y0, x1, y1):
        self.x0 = min(self.x0, x0, x1)
        self.x1 = max(self.x1, x0, x1)
        self.y0 = min(self.y0, y0, y1)
        self.y1 = max(self.y1, y0, y1)

    @property
    def valid(self):
        return self.x1 > -1e8

    @property
    def top(self):
        return self.y1

    @property
    def left(self):
        return self.x0


def _mul(a, b):
    return (a[0] * b[0] + a[1] * b[2], a[0] * b[1] + a[1] * b[3],
            a[2] * b[0] + a[3] * b[2], a[2] * b[1] + a[3] * b[3],
            a[4] * b[0] + a[5] * b[2] + b[4], a[4] * b[1] + a[5] * b[3] + b[5])


def _parse_tounicode(raw: bytes):
    m, txt = {}, raw.decode("latin-1", "replace")
    for blk in re.findall(r"beginbfchar(.*?)endbfchar", txt, re.S):
        for s, d in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", blk):
            try:
                m[int(s, 16)] = "".join(chr(int(d[i:i + 4], 16)) for i in range(0, len(d), 4))
            except ValueError:
                pass
    for blk in re.findall(r"beginbfrange(.*?)endbfrange", txt, re.S):
        for lo, hi, d in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", blk):
            try:
                lo_i, hi_i, di = int(lo, 16), int(hi, 16), int(d, 16)
                for k in range(lo_i, min(hi_i, lo_i + 65535) + 1):
                    m[k] = chr(di + (k - lo_i))
            except ValueError:
                pass
    return m


def _fonts(res, cache):
    out = {}
    fd = res.get("/Font") if res is not None else None
    if fd is None:
        return out
    for key, fobj in fd.items():
        try:
            oid = fobj.objgen
        except Exception:
            oid = None
        if oid in cache:
            out[str(key)] = cache[oid]
            continue
        two = fobj.get("/Subtype") == Name("/Type0") or "Identity" in str(fobj.get("/Encoding"))
        tou = {}
        if "/ToUnicode" in fobj:
            try:
                tou = _parse_tounicode(bytes(fobj["/ToUnicode"].read_bytes()))
            except Exception:
                pass
        base = str(fobj.get("/BaseFont") or "")
        info = (two, tou, base)
        cache[oid] = info
        out[str(key)] = info
    return out


def _decode(raw: bytes, finfo):
    if finfo is None:
        return raw.decode("latin-1", "replace")
    two, tou, _ = finfo
    if two:
        return "".join(tou.get((raw[i] << 8) | raw[i + 1], "?") for i in range(0, len(raw) - 1, 2))
    return "".join(tou.get(b, chr(b)) for b in raw)


def page_mcid_boxes(page, cache=None):
    """
    {mcid: BBox} for one page (recursing into Form XObjects).

    Text and image XObjects define the box.  Pure vector art (illustrations
    drawn with path operators) has neither, so its path extents are used as a
    fallback - clamped to the page box, because clip rectangles and stray
    control points otherwise blow the bbox up to absurd sizes and every
    box-vs-photo heuristic downstream then misfires.
    """
    cache = {} if cache is None else cache
    boxes, pboxes = {}, {}
    _walk(page.obj, page.get("/Resources") or Dictionary(), boxes, cache,
          (1, 0, 0, 1, 0, 0), 0, pboxes)
    mb = page.mediabox
    px0, py0 = float(mb[0]), float(mb[1])
    px1, py1 = float(mb[2]), float(mb[3])
    for m, b in pboxes.items():
        if m in boxes and boxes[m].valid:
            continue
        if not b.valid:
            continue
        b.x0 = max(b.x0, px0); b.y0 = max(b.y0, py0)
        b.x1 = min(b.x1, px1); b.y1 = min(b.y1, py1)
        if b.x1 > b.x0 and b.y1 > b.y0:
            boxes[m] = b
    return boxes


def _walk(obj, res, boxes, cache, ctm, depth, pboxes=None):
    if depth > 4:
        return
    if pboxes is None:
        pboxes = {}
    fonts = _fonts(res, cache)
    try:
        instrs = pikepdf.parse_content_stream(obj)
    except Exception:
        return

    stack, cur = [], None            # marked-content stack, current mcid
    tm = tlm = (1, 0, 0, 1, 0, 0)
    leading = 0.0
    size = 12.0
    finfo = None
    gs, cm = [], ctm

    for ops, op in instrs:
        o = str(op)
        try:
            if o == "q":
                gs.append(cm)
            elif o == "Q":
                if gs:
                    cm = gs.pop()
            elif o == "cm":
                cm = _mul(tuple(float(x) for x in ops), cm)
            elif o in ("BDC", "BMC"):
                tag = str(ops[0]) if ops else "?"
                mcid = None
                if o == "BDC" and len(ops) > 1:
                    p = ops[1]
                    if isinstance(p, Dictionary) and "/MCID" in p:
                        mcid = int(p["/MCID"])
                    elif isinstance(p, Name):
                        props = res.get("/Properties")
                        if props is not None and str(p) in [str(k) for k in props.keys()]:
                            d = props[str(p)]
                            if "/MCID" in d:
                                mcid = int(d["/MCID"])
                stack.append((tag, mcid))
                cur = mcid if not any(t == "/Artifact" for t, _ in stack) else None
            elif o == "EMC":
                if stack:
                    stack.pop()
                cur = None
                for t, m in reversed(stack):
                    if t == "/Artifact":
                        cur = None
                        break
                    if m is not None:
                        cur = m
                        break
            elif o == "BT":
                tm = tlm = (1, 0, 0, 1, 0, 0)
            elif o == "Tf":
                finfo = fonts.get(str(ops[0]))
                size = float(ops[1])
            elif o == "TL":
                leading = float(ops[0])
            elif o == "Tm":
                tm = tlm = tuple(float(x) for x in ops)
            elif o == "Td":
                tlm = _mul((1, 0, 0, 1, float(ops[0]), float(ops[1])), tlm)
                tm = tlm
            elif o == "TD":
                leading = -float(ops[1])
                tlm = _mul((1, 0, 0, 1, float(ops[0]), float(ops[1])), tlm)
                tm = tlm
            elif o == "T*":
                tlm = _mul((1, 0, 0, 1, 0, -leading), tlm)
                tm = tlm
            elif o in ("Tj", "TJ", "'", '"'):
                if o in ("'", '"'):
                    tlm = _mul((1, 0, 0, 1, 0, -leading), tlm)
                    tm = tlm
                if cur is None:
                    continue
                txt = ""
                if o == "TJ":
                    for el in ops[0]:
                        if isinstance(el, pikepdf.String):
                            txt += _decode(bytes(el), finfo)
                else:
                    s = ops[-1]
                    if isinstance(s, pikepdf.String):
                        txt = _decode(bytes(s), finfo)
                if not txt:
                    continue
                trm = _mul(tm, cm)
                eff = size * (abs(trm[3]) if abs(trm[3]) > 1e-6 else 1.0) / (abs(tm[3]) or 1.0) if False else size * abs(_mul(tm, cm)[3] / (tm[3] if tm[3] else 1))
                eff = abs(size * (tm[3] if tm[3] else 1) * (cm[3] if cm[3] else 1))
                b = boxes.setdefault(cur, BBox())
                b.add(trm[4], trm[5], eff, len(txt))
                b.chars += len(txt.strip())
                b.text += txt
                b.sizes.append(round(eff, 2))
                if finfo:
                    b.fonts.append(finfo[2])
            elif o in ("re", "m", "l", "c", "v", "y") and cur is not None:
                # vector art: illustrations drawn as paths, not image XObjects.
                # Without this they have no bbox and every downstream fixer
                # silently skips them.
                v = [float(x) for x in ops]
                pts = []
                if o == "re" and len(v) == 4:
                    pts = [(v[0], v[1]), (v[0] + v[2], v[1] + v[3])]
                else:
                    pts = [(v[i], v[i + 1]) for i in range(0, len(v) - 1, 2)]
                b = pboxes.setdefault(cur, BBox())
                for px, py in pts:
                    gx = px * cm[0] + py * cm[2] + cm[4]
                    gy = px * cm[1] + py * cm[3] + cm[5]
                    b.add_rect(gx, gy, gx, gy)

            elif o == "Do":
                xod = res.get("/XObject")
                if xod is None:
                    continue
                xo = xod.get(str(ops[0]))
                if xo is not None and xo.get("/Subtype") == Name("/Image") and cur is not None:
                    # image occupies the unit square mapped through the CTM
                    xs = [cm[4], cm[0] + cm[4], cm[2] + cm[4], cm[0] + cm[2] + cm[4]]
                    ys = [cm[5], cm[1] + cm[5], cm[3] + cm[5], cm[1] + cm[3] + cm[5]]
                    _b = boxes.setdefault(cur, BBox())
                    _b.add_rect(min(xs), min(ys), max(xs), max(ys))
                    _b.is_image = True
                if xo is not None and xo.get("/Subtype") == Name("/Form"):
                    sub = xo.get("/Resources") or res
                    nctm = cm
                    mtx = xo.get("/Matrix")
                    if mtx is not None:
                        nctm = _mul(tuple(float(x) for x in mtx), cm)
                    _walk(xo, sub, boxes, cache, nctm, depth + 1, pboxes)
        except Exception:
            continue


def document_mcid_boxes(pdf):
    """{(page_index, mcid): BBox} for the whole document."""
    cache, out = {}, {}
    for i, page in enumerate(pdf.pages):
        for m, b in page_mcid_boxes(page, cache).items():
            out[(i, m)] = b
    return out
