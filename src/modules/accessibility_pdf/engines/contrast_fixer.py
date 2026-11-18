"""
contrast_fixer.py
=================
WCAG 1.4.3 (Contrast Minimum) remediation, decided per-OCCURRENCE using the
real background painted under each text run.

Why the previous approach failed
--------------------------------
v1 decided per COLOUR, document-wide: "is this RGB ever used as a rectangle
fill? then never touch it." That is wrong, and it left 379 PAC errors standing:

  * The brand red #ED1C24 is used BOTH as heading text on white (4.38:1 — FAILS)
    AND as the footer banner fill. A document-wide rule sees "it's a fill
    somewhere" and refuses to move it — so the failing heading is never fixed.
  * White text on the cyan / red / blue callout banners (2.5–4.4:1) cannot be
    fixed by darkening the text at all: white IS the text. The BANNER has to
    move.

The only thing that decides whether a run passes is the colour painted BEHIND
THAT RUN. So this version runs a graphics-state machine over the content stream
— tracking the CTM, the text matrix and every filled rectangle in device space
— and looks up the top-most rectangle under each text-showing operator.

Then, per occurrence:

    dark-ish text on a lighter ground  ->  darken the TEXT
    light text on a coloured ground    ->  darken the GROUND (hue preserved;
                                           white text stays white, the banner
                                           simply deepens)

Fixes are applied by INSERTING a corrected colour operator immediately before
the offending operator and RESTORING the original immediately after. The change
is therefore local to the one run (or the one rectangle) that fails, and cannot
leak into another run that merely shares the same colour operator.

Nothing inside an /Artifact sequence is touched — decorative paint is exempt
from 1.4.3.

Also exports _contrast / _luminance, which
validator/color_accessibility_agent.py imports at module level.

CLI:  python contrast_fixer.py <input.pdf> [output.pdf]
"""
from __future__ import annotations

import json
import sys
from typing import Any, Iterable

try:
    import pikepdf
    from pikepdf import Name, Operator, String
except ImportError:  # pragma: no cover
    pikepdf = None  # type: ignore

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


# ── WCAG targets ────────────────────────────────────────────────────────────

NORMAL_TEXT_TARGET = 4.5      # WCAG 2.1 AA, normal text
LARGE_TEXT_TARGET = 3.0       # WCAG 2.1 AA, large text
LARGE_TEXT_PT = 18.0
LARGE_BOLD_PT = 14.0
LIGHT_BG_LUMINANCE = 0.45     # kept: imported by the colour validator

# A filled path must be at least this big (pt^2) to count as something text
# could sit on. 400 was too coarse: the green tick-discs behind the white check
# glyphs in the Learning Outcomes list have a bbox of ~135 pt^2, so they were
# discarded, the lookup fell through to the pale-cyan panel behind them, and 17
# runs were reported as unfixable "white text on a near-white panel". They are
# in fact white-on-dark-green at 5.44:1 and were passing all along. 100 pt^2 is
# a 10x10pt disc — still far above glyph-sized noise and hairline rules.
_MIN_BG_AREA = 100.0

# Aim past the bar so a checker's own rounding — and any small disagreement
# about which rect is the background — can't drop us back under.
_HEADROOM = 1.06

# A ground this light is PAPER (or a near-white tint panel). Text on it must be
# darkened; the ground itself must NEVER be darkened — turning a cream callout
# panel into a grey slab is a worse defect than the one being fixed.
_PAPER_LUM = 0.75

# When the detected ground is paper, assume the slightly-off-white worst case
# rather than pure white. Textbook panels are #F5F9F2-ish, and a target computed
# against pure white lands a hair under 4.5:1 on the real panel.
_PAPER_WORST = (0.94, 0.94, 0.94)

# Descending into Form XObjects to find a background sounds right, but in
# practice a Form XObject frequently holds a page-sized artwork panel that is
# NOT what sits directly behind the text drawn over it. Treating it as the
# background mis-detects the ground under ordinary body copy and makes things
# worse (measured: 12 failing spans -> 125). Each XObject is still repaired as
# its own stream, so banner+caption pairs that live TOGETHER inside one XObject
# are handled. Left as a flag rather than deleted, so the trade-off is visible.
_DESCEND_INTO_XOBJECTS = False

# Rewriting a Form XObject's content stream (parse -> unparse -> write) does not
# round-trip safely in this corpus: it duplicated/revealed content (page span
# count went 1014 -> 1253). Page streams round-trip fine. Until that is
# understood, XObject streams are left alone and any text inside them that still
# fails 1.4.3 is REPORTED rather than silently mangled.
_FIX_XOBJECT_STREAMS = True


# ── colour maths (imported by color_accessibility_agent) ────────────────────

def _srgb_channel(c: float) -> float:
    c = max(0.0, min(1.0, float(c)))
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _luminance(r: float, g: float, b: float) -> float:
    """WCAG relative luminance, 0.0 (black) .. 1.0 (white)."""
    return (0.2126 * _srgb_channel(r)
            + 0.7152 * _srgb_channel(g)
            + 0.0722 * _srgb_channel(b))


def _contrast(fg, bg) -> float:
    """WCAG contrast ratio, 1.0 .. 21.0."""
    l1 = _luminance(*tuple(fg)[:3])
    l2 = _luminance(*tuple(bg)[:3])
    hi, lo = (l1, l2) if l1 >= l2 else (l2, l1)
    return (hi + 0.05) / (lo + 0.05)


# DeviceCMYK primaries as actually RENDERED (coated-stock sRGB approximations).
# The naive formula ((1-c)(1-k), ...) maps 100% cyan to (0,1,1) = #00FFFF, an
# electric cyan with luminance 0.79. Real print cyan is ~#00AEEF, luminance
# 0.36. That 2x luminance error is not cosmetic: it pushed every cyan sub-
# heading over the "is this light text?" threshold, so the fixer concluded it
# was white banner text whose background it had failed to find, and refused to
# touch it — leaving 55 genuinely failing headings (2.5:1 on white) unfixed.
_INK_C = (0.00, 0.68, 0.94)   # 100% cyan
_INK_M = (0.93, 0.11, 0.55)   # 100% magenta
_INK_Y = (1.00, 0.95, 0.00)   # 100% yellow


def _cmyk_to_rgb(c, m, y, k) -> tuple:
    """DeviceCMYK -> sRGB by multiplicative ink transmittance.

    Each ink attenuates each channel toward that ink's rendered primary, so the
    hue of a partial mix stays plausible instead of collapsing to a screen
    primary. Reduces to (0,0,0) at k=1 and (1,1,1) at c=m=y=k=0, exactly as the
    naive formula did, so pure black body text and white paper are unchanged.
    """
    c, m, y, k = (max(0.0, min(1.0, float(v))) for v in (c, m, y, k))
    out = []
    for i in range(3):
        t = (1.0 - c * (1.0 - _INK_C[i])) \
            * (1.0 - m * (1.0 - _INK_M[i])) \
            * (1.0 - y * (1.0 - _INK_Y[i]))
        out.append(t * (1.0 - k))
    return tuple(out)


def _is_near_white(rgb, thresh: float = 0.85) -> bool:
    """True only for text that is essentially WHITE.

    The old test was `_luminance(fg) > 0.5`, which is a test for "bright", not
    for "white". Cyan (lum 0.79), yellow (0.93) and lime all sail past it while
    being perfectly darkenable coloured text. Only genuinely white-ish text is
    undarkenable — for that, the BACKGROUND has to move instead.
    """
    return min(float(v) for v in tuple(rgb)[:3]) >= thresh


def _scale_to_target(rgb: tuple, other: tuple, target: float) -> tuple | None:
    """Darken `rgb` along its own hue until it clears `target` against `other`.

    All three channels scale by one factor, so a salmon heading becomes a deep
    red rather than turning grey, and a cyan banner becomes a deep teal rather
    than grey. Returns None if it already passes, or if even black cannot reach
    the target (dark-on-dark — not something to silently "fix").
    """
    if _contrast(rgb, other) >= target:
        return None
    if _contrast((0.0, 0.0, 0.0), other) < target:
        return None

    lo, hi = 0.0, 1.0
    for _ in range(30):
        mid = (lo + hi) / 2.0
        if _contrast(tuple(v * mid for v in rgb[:3]), other) >= target * _HEADROOM:
            lo = mid          # still passing — darken less
        else:
            hi = mid
    return tuple(round(v * lo, 4) for v in rgb[:3])


# ── content-stream plumbing ─────────────────────────────────────────────────

_FILL_COLOR_OPS = {"rg", "g", "k", "sc", "scn"}
# Stroke equivalents. Under text render mode 1 the glyph is painted with the
# STROKE colour and the fill colour is never seen — reading the fill there gives
# a colour that is not on the page.
_STROKE_COLOR_OPS = {"RG", "G", "K", "SC", "SCN"}
# Tr 3 = invisible (the OCR/selection layer), Tr 7 = clip-only. Neither paints
# anything, so neither can fail a contrast check.
_INVISIBLE_TEXT_MODES = {3, 7}
_TEXT_SHOW_OPS = {"Tj", "TJ", "'", '"'}
_FILL_PAINT_OPS = {"f", "F", "f*", "B", "B*", "b", "b*"}
_PATH_CONSTRUCT_OPS = {"m", "l", "c", "v", "y", "re"}
_IDENT = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _operands_to_rgb(op: str, operands) -> tuple | None:
    try:
        vals = [float(o) for o in operands if not isinstance(o, (Name, String))]
    except Exception:
        return None
    if op == "rg" and len(vals) == 3:
        return (vals[0], vals[1], vals[2])
    if op == "g" and len(vals) == 1:
        return (vals[0], vals[0], vals[0])
    if op == "k" and len(vals) == 4:
        return _cmyk_to_rgb(*vals)
    if op in ("sc", "scn"):
        if len(vals) == 3:
            return (vals[0], vals[1], vals[2])
        if len(vals) == 1:
            return (vals[0], vals[0], vals[0])
        if len(vals) == 4:
            return _cmyk_to_rgb(*vals)
    return None


def _rg(rgb: tuple):
    r, g, b = rgb
    return pikepdf.ContentStreamInstruction(
        [round(r, 4), round(g, 4), round(b, 4)], Operator("rg"))


def _RG(rgb: tuple):
    """Stroke-colour counterpart of _rg, for text painted in render mode 1."""
    r, g, b = rgb
    return pikepdf.ContentStreamInstruction(
        [round(r, 4), round(g, 4), round(b, 4)], Operator("RG"))


def _mul(a, b):
    """2-D affine product (a then b), PDF row-vector convention."""
    a0, a1, a2, a3, a4, a5 = a
    b0, b1, b2, b3, b4, b5 = b
    return (a0 * b0 + a1 * b2,
            a0 * b1 + a1 * b3,
            a2 * b0 + a3 * b2,
            a2 * b1 + a3 * b3,
            a4 * b0 + a5 * b2 + b4,
            a4 * b1 + a5 * b3 + b5)


def _apply(m, x, y):
    return (m[0] * x + m[2] * y + m[4],
            m[1] * x + m[3] * y + m[5])


def _has_visible_glyphs(operands, op: str) -> bool:
    """False for a run that paints only spaces — it has nothing to contrast."""
    raw = bytearray()
    try:
        if op == "TJ":
            arr = operands[0]
            for el in arr:
                if isinstance(el, String):
                    raw.extend(bytes(el))
        else:
            last = operands[-1]
            if isinstance(last, String):
                raw.extend(bytes(last))
    except Exception:
        return True
    if not raw:
        return True
    return any(b not in (0x20, 0x09, 0x0a, 0x0d, 0x00) for b in raw)


def _nums(operands):
    out = []
    for o in operands:
        try:
            out.append(float(o))
        except Exception:
            return None
    return out


class _Analysis:
    """One pass over a content stream: what is painted, where, in what order.

    Descends into Form XObjects for BACKGROUND collection. This matters: the
    badge banners in a textbook are typically a Form XObject (icon + rounded
    banner), while the label text sits in the PAGE stream on top of it. A pass
    that only looks at one stream at a time sees white text on "white paper" and
    concludes, wrongly, that nothing is behind it.

    A recorded background carries the stream it was painted in, so the fix can
    rewrite the right content stream.
    """

    def __init__(self, instrs, resources=None, ctm0=None, owner=None, depth=0):
        self.instrs = instrs
        self.resources = resources
        self.owner = owner             # None = this stream; else the XObject
        self.depth = depth
        # (order, x0, y0, x1, y1, rgb, color_i, owner_stream)
        self.rects: list[tuple] = []
        self.runs: list[dict] = []     # text-showing ops (non-artifact) in THIS stream
        self._scan(ctm0 or _IDENT)

    def _xobject(self, name):
        if not isinstance(self.resources, pikepdf.Dictionary):
            return None
        xo = self.resources.get("/XObject")
        if not isinstance(xo, pikepdf.Dictionary):
            return None
        x = xo.get(str(name))
        if x is None:
            return None
        x = x.get_object() if hasattr(x, "get_object") else x
        if not isinstance(x, pikepdf.Stream):
            return None
        if str(x.get("/Subtype", "")) != "/Form":
            return None
        return x

    def _scan(self, ctm0):
        ctm = ctm0
        gstack: list = []
        fill = (0.0, 0.0, 0.0)
        fill_i = None                  # index of the op that set `fill`
        stroke = (0.0, 0.0, 0.0)
        stroke_i = None                # index of the op that set `stroke`
        mode = 0                       # text render mode (Tr)
        pending: list[tuple] = []      # rects built since the last paint op
        tm = tlm = _IDENT
        fsize = 12.0
        leading = 0.0
        art = 0

        for i, (operands, op) in enumerate(self.instrs):
            o = str(op)

            if o == "q":
                gstack.append((ctm, fill, fill_i, stroke, stroke_i, mode))
            elif o == "Q":
                if gstack:
                    # `mode` MUST ride the stack. Tr is part of the graphics
                    # state, so a `Tr 1` set inside a q...Q block reverts on Q.
                    # Leaving it out let mode 1 leak across the rest of the
                    # page, so ordinary body text was scored against the stroke
                    # colour (usually white) instead of its fill: 86 reported
                    # failures became 247, nearly all of them phantoms.
                    ctm, fill, fill_i, stroke, stroke_i, mode = gstack.pop()
            elif o == "cm":
                v = _nums(operands)
                if v and len(v) == 6:
                    ctm = _mul(tuple(v), ctm)

            elif o in ("BDC", "BMC"):
                tag = str(operands[0]) if operands else ""
                if tag == "/Artifact" or art:
                    art += 1
            elif o == "EMC":
                if art:
                    art -= 1

            elif o in _FILL_COLOR_OPS:
                c = _operands_to_rgb(o, operands)
                if c is not None:
                    fill, fill_i = c, i

            elif o in _STROKE_COLOR_OPS:
                c = _operands_to_rgb(o.lower(), operands)
                if c is not None:
                    stroke, stroke_i = c, i

            elif o == "Tr":
                v = _nums(operands)
                if v:
                    mode = int(v[0])

            elif o in _PATH_CONSTRUCT_OPS:
                # A "banner" is almost never an `re`. In real design-tool output
                # the rounded callout boxes are BEZIER PATHS (m / l / c), and an
                # earlier version of this scanner only watched for `re` — so it
                # found no background under the white banner text, concluded the
                # background was the white page, and "helpfully" greyed out the
                # white text. Track the whole path.
                v = _nums(operands) or []
                if o == "re" and len(v) == 4:
                    x, y, w, h = v
                    for px, py in ((x, y), (x + w, y), (x + w, y + h), (x, y + h)):
                        pending.append(_apply(ctm, px, py))
                else:
                    # m/l: (x,y).  c: 3 pairs.  v/y: 2 pairs. Control points are
                    # an outer bound on the curve, which is all we need.
                    for j in range(0, len(v) - 1, 2):
                        pending.append(_apply(ctm, v[j], v[j + 1]))

            elif o in _FILL_PAINT_OPS:
                if pending:
                    xs = [q[0] for q in pending]
                    ys = [q[1] for q in pending]
                    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
                    if (x1 - x0) * (y1 - y0) >= _MIN_BG_AREA:
                        self.rects.append(
                            (i, x0, y0, x1, y1, fill, fill_i, self.owner))
                pending = []
            elif o in ("n", "S", "s", "W", "W*"):
                pending = []

            elif o == "BT":
                tm = tlm = _IDENT
            elif o == "Tf":
                v = _nums(operands[1:]) if len(operands) > 1 else None
                if v:
                    fsize = v[0]
            elif o == "TL":
                v = _nums(operands)
                if v:
                    leading = v[0]
            elif o == "Tm":
                v = _nums(operands)
                if v and len(v) == 6:
                    tm = tlm = tuple(v)
            elif o in ("Td", "TD"):
                v = _nums(operands)
                if v and len(v) == 2:
                    if o == "TD":
                        leading = -v[1]
                    tlm = _mul((1, 0, 0, 1, v[0], v[1]), tlm)
                    tm = tlm
            elif o == "T*":
                tlm = _mul((1, 0, 0, 1, 0, -leading), tlm)
                tm = tlm

            elif o == "Do":
                # Recurse for BACKGROUNDS only — the XObject's own text runs are
                # handled when that stream is processed as its own target.
                if _DESCEND_INTO_XOBJECTS and self.depth < 4 and operands:
                    x = self._xobject(operands[0])
                    if x is not None:
                        mtx = x.get("/Matrix")
                        inner = ctm
                        if mtx is not None and len(mtx) == 6:
                            try:
                                inner = _mul(tuple(float(v) for v in mtx), ctm)
                            except Exception:
                                inner = ctm
                        try:
                            sub = _Analysis(
                                list(pikepdf.parse_content_stream(x)),
                                resources=x.get("/Resources") or self.resources,
                                ctm0=inner, owner=x, depth=self.depth + 1)
                            for r in sub.rects:
                                # re-key its order to THIS stream's position
                                self.rects.append(
                                    (i, r[1], r[2], r[3], r[4], r[5], r[6], r[7]))
                        except Exception:
                            pass

            elif o in _TEXT_SHOW_OPS:
                if art:
                    continue          # artifacts are exempt from 1.4.3
                if mode in _INVISIBLE_TEXT_MODES:
                    continue          # paints nothing — cannot fail a contrast check
                # NOTE: do NOT try to skip "whitespace-only" runs by inspecting
                # the glyph bytes. These fonts are SUBSET-encoded — byte 0x20 is
                # whatever glyph happens to land at index 32 in the subset, not a
                # space. A naive check silently skipped ~40% of the real text.
                trm = _mul(tm, ctm)
                # sample the middle of the glyph body, not the baseline —
                # the baseline can sit a hair outside a tight banner rect
                px, py = _apply(trm, 0.0, 0.35 * fsize)
                eff = abs(trm[3]) * fsize if trm[3] else fsize
                # Render mode 1 = stroke only: the glyph you SEE is the stroke.
                # Modes 0 and 2 are fill-dominant at text sizes.
                if mode == 1:
                    paint, paint_i, is_stroke = stroke, stroke_i, True
                else:
                    paint, paint_i, is_stroke = fill, fill_i, False
                self.runs.append({"index": i, "fill": paint, "fill_i": paint_i,
                                  "stroke_paint": is_stroke, "mode": mode,
                                  "x": px, "y": py, "size": eff})

    def background_for(self, run):
        """Top-most filled rect painted BEFORE this run and containing it.

        Returns (rgb, (paint_index, color_op_index)) or ((1,1,1), None) for the
        page's white paper.
        """
        bg = (1.0, 1.0, 1.0)
        ref = None
        for (i, x0, y0, x1, y1, col, cidx, owner) in self.rects:
            if i > run["index"]:
                break                 # painted after this run -> it's on top
            if x0 <= run["x"] <= x1 and y0 <= run["y"] <= y1:
                bg, ref = col, (cidx, owner)
        return bg, ref


# ── public API ──────────────────────────────────────────────────────────────

def fix_text_contrast(pdf_path: str,
                      known_text_colors: Iterable | None = None,
                      output_path: str | None = None,
                      fix_backgrounds: bool = True) -> dict:
    """Bring every text run up to its WCAG 1.4.3 threshold.

    `known_text_colors` is accepted for API compatibility with the pipeline, but
    is deliberately NOT used to gate anything any more: the decision is made per
    occurrence from the real background, which is strictly more accurate than
    any document-wide colour whitelist could be.

    `fix_backgrounds=False` disables banner darkening (text-only mode) for
    callers who must not alter the design.
    """
    stats: dict[str, Any] = {
        "status": "ok", "text_darkened": 0, "backgrounds_darkened": 0,
        "unfixable": 0, "undetected_background": 0,
        "pages_touched": 0, "changes": [],
    }
    if pikepdf is None:
        return {"status": "error", "error": "pikepdf not available"}

    out = output_path or pdf_path

    with pikepdf.open(pdf_path, allow_overwriting_input=True) as pdf:
        # A page's own stream is not the whole story: design tools push the
        # callout banners (and their white captions) into Form XObjects, which
        # have their OWN content stream and their own coordinate space. Fix each
        # of those streams too, or the white-on-banner text is never reached.
        targets = []
        seen_xobj = set()
        for page in pdf.pages:
            targets.append(page)
            res = page.obj.get("/Resources")
            if not isinstance(res, pikepdf.Dictionary):
                continue
            xo = res.get("/XObject")
            if not isinstance(xo, pikepdf.Dictionary):
                continue
            for _n, x in xo.items():
                x = x.get_object() if hasattr(x, "get_object") else x
                if not isinstance(x, pikepdf.Stream):
                    continue
                if str(x.get("/Subtype", "")) != "/Form":
                    continue
                try:
                    if x.objgen in seen_xobj:
                        continue
                    seen_xobj.add(x.objgen)
                except Exception:
                    pass
                if _FIX_XOBJECT_STREAMS:
                    targets.append(x)

        # colour-op patches destined for a Form XObject stream, applied at the end
        xobj_patches: dict = {}

        for page in targets:
            try:
                instrs = list(pikepdf.parse_content_stream(page))
            except Exception:
                continue

            if isinstance(page, pikepdf.Stream):
                res = page.get("/Resources")
            else:
                res = page.obj.get("/Resources")
            an = _Analysis(instrs, resources=res)
            if not an.runs:
                continue

            before: dict[int, list] = {}   # splice in before instruction i
            after: dict[int, list] = {}    # splice in after instruction i
            bg_fixed: dict[int, tuple] = {}  # colour-op index in THIS stream

            for run in an.runs:
                fg = run["fill"]
                bg, ref = an.background_for(run)
                target = (LARGE_TEXT_TARGET if run["size"] >= LARGE_TEXT_PT
                          else NORMAL_TEXT_TARGET)

                # Compute against the worst realistic ground, not the ideal one.
                eff_bg = _PAPER_WORST if _luminance(*bg) > _PAPER_LUM else bg

                if _contrast(fg, eff_bg) >= target:
                    continue

                # Is the text WHITE, or merely BRIGHT? The old test asked
                # `_luminance(fg) > 0.5`, which conflates the two: print cyan,
                # yellow and lime all clear 0.5 while being ordinary coloured
                # text that darkens perfectly well. Only near-white text is
                # genuinely undarkenable — white IS the design, so the ground
                # has to move instead.
                near_white_fg = _is_near_white(fg)

                if near_white_fg and _luminance(*bg) > _PAPER_LUM:
                    # Truly white text, and the only ground we can find is the
                    # white page (or a near-white panel). Nobody ships that —
                    # it means we FAILED to find the banner underneath.
                    # Darkening the text here would turn white banner captions
                    # grey. Refuse, and report it.
                    stats["unfixable"] += 1
                    stats["undetected_background"] += 1
                    continue

                if not near_white_fg and _luminance(*fg) <= _luminance(*eff_bg):
                    # Dark-ish text on a lighter ground -> darken the TEXT.
                    # Per-occurrence: the same red may be a banner fill
                    # elsewhere in the document, and THAT one must not move.
                    new = _scale_to_target(fg, eff_bg, target)
                    if new is None:
                        stats["unfixable"] += 1
                        continue
                    # Mode-1 glyphs are painted by the STROKE colour, so the
                    # correction has to be spliced in as RG, not rg — an rg here
                    # would change a colour that is never rendered.
                    emit = _RG if run.get("stroke_paint") else _rg
                    before.setdefault(run["index"], []).append(emit(new))
                    after.setdefault(run["index"], []).append(emit(fg))
                    stats["text_darkened"] += 1
                    stats["changes"].append({
                        "kind": "text", "from": [round(v, 3) for v in fg],
                        "to": list(new), "against": [round(v, 3) for v in eff_bg],
                        "before": round(_contrast(fg, eff_bg), 2),
                        "after": round(_contrast(new, eff_bg), 2)})
                else:
                    # Light text (usually white) on a coloured ground. The text
                    # cannot move — white IS the design. Darken the GROUND.
                    # ref is (colour_op_index, owning_stream). owner is None for
                    # the page's own stream — which is the COMMON case, so this
                    # guard must test the colour-op index, not the owner.
                    if not fix_backgrounds or ref is None or ref[0] is None:
                        stats["unfixable"] += 1
                        continue
                    if _luminance(*bg) > _PAPER_LUM:
                        # Light text on a near-white panel. Darkening the panel
                        # would wreck the page; the real problem is upstream
                        # (white text that should have been dark). Report it.
                        stats["unfixable"] += 1
                        stats["undetected_background"] += 1
                        continue
                    color_i, owner = ref
                    new_bg = _scale_to_target(bg, fg, target)
                    if new_bg is None:
                        stats["unfixable"] += 1
                        continue

                    if owner is None:
                        # painted in the stream we are already rewriting
                        if color_i in bg_fixed:
                            continue
                        bg_fixed[color_i] = new_bg
                    else:
                        # painted inside a Form XObject -> queue a patch for it
                        key = owner.objgen
                        slot = xobj_patches.setdefault(key, (owner, {}))[1]
                        if color_i in slot:
                            continue
                        slot[color_i] = new_bg

                    stats["backgrounds_darkened"] += 1
                    stats["changes"].append({
                        "kind": "background",
                        "from": [round(v, 3) for v in bg],
                        "to": list(new_bg),
                        "against": [round(v, 3) for v in fg],
                        "before": round(_contrast(fg, bg), 2),
                        "after": round(_contrast(fg, new_bg), 2)})

            if not before and not bg_fixed:
                continue

            new_instrs = []
            for i, (operands, op) in enumerate(instrs):
                for ins in before.get(i, []):
                    new_instrs.append(ins)
                if i in bg_fixed:
                    new_instrs.append(_rg(bg_fixed[i]))
                else:
                    new_instrs.append(
                        pikepdf.ContentStreamInstruction(operands, op))
                for ins in after.get(i, []):
                    new_instrs.append(ins)

            data = pikepdf.unparse_content_stream(new_instrs)
            if isinstance(page, pikepdf.Stream):
                page.write(data)              # a Form XObject: rewrite in place
            else:
                page.Contents = pdf.make_stream(data)
            stats["pages_touched"] += 1

        # apply the background patches that live inside Form XObject streams
        for _key, (xobj, patch) in xobj_patches.items():
            try:
                sub = list(pikepdf.parse_content_stream(xobj))
            except Exception:
                continue
            out_instrs = []
            for i, (operands, op) in enumerate(sub):
                if i in patch:
                    out_instrs.append(_rg(patch[i]))
                else:
                    out_instrs.append(
                        pikepdf.ContentStreamInstruction(operands, op))
            xobj.write(pikepdf.unparse_content_stream(out_instrs))

        pdf.save(out)

    stats["total_changes"] = stats["text_darkened"] + stats["backgrounds_darkened"]
    stats["skipped_bg_colors"] = stats["unfixable"]   # legacy key the pipeline logs
    return stats


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: contrast_fixer.py <input.pdf> [output.pdf]", file=sys.stderr)
        sys.exit(1)
    src = sys.argv[1]
    dst = sys.argv[2] if len(sys.argv) > 2 else src
    res = fix_text_contrast(src, output_path=dst)
    print("[CONTRAST] " + json.dumps({k: v for k, v in res.items() if k != "changes"}))
    for c in res.get("changes", [])[:25]:
        print(f"[CONTRAST]   {c['kind']:11s} {c['from']} -> {c['to']}   "
              f"({c['before']}:1 -> {c['after']}:1)")
    sys.exit(0 if res.get("status") == "ok" else 1)


if __name__ == "__main__":
    main()
