#!/usr/bin/env python3
"""
struct_parent_fixer.py

Repairs structure-element /P (parent) back-pointers so that every element's
declared parent matches the element that actually contains it in /K.

Why this exists
---------------
Every StructElem carries a /P entry pointing back at its parent. When a fixer
MOVES a child between parents (e.g. paragraph_merge_fixer merging two <P>
elements, or a heading/figure re-parent step) and forgets to update the moved
child's /P, the back-pointer goes stale — it still points at the old parent,
which is often an element that has since been detached from the tree entirely.

PAC reports this as:

    "Structure element refers to a diffrent parent than the actual parent"

and counts it under BOTH "Parents of structure elements" and "Logical structure
syntax" — so 2 broken elements surface as 4 errors.

Screen readers generally follow /K (downward), so this is usually a validity
defect rather than a content-loss defect. But it is a PDF/UA hard failure and
it signals a genuinely corrupt tree, so it must be repaired.

Fix
---
Walk the structure tree from StructTreeRoot. For every element reached via a
parent's /K, set its /P to that actual parent. Top-level elements get /P =
StructTreeRoot. This is authoritative (/K defines real containment) and
idempotent — running it twice changes nothing the second time.

Also reports (and optionally removes) elements that are unreachable from the
root but still referenced by a stale /P — those are the detached leftovers
that caused the mismatch in the first place.

Usage
-----
    python3 struct_parent_fixer.py <input.pdf> <output.pdf>
"""

from __future__ import annotations

import json
import sys

import pikepdf


def _kids(node):
    k = node.get("/K")
    if k is None:
        return []
    return list(k) if isinstance(k, pikepdf.Array) else [k]


def _og(obj):
    try:
        return obj.objgen if obj is not None and obj.is_indirect else None
    except Exception:
        return None


# Operators that put marks on the page. Kept in step with validate.PAINT.
_PAINT_OPS = {
    "Tj", "TJ", "'", '"',
    "S", "s", "f", "F", "f*", "B", "B*", "b", "b*", "sh",
    "Do",
}


def _present_mcids(pdf):
    """(page_index) -> MCIDs on that page that correspond to REAL content.

    "Real" means the sequence either paints something (text, image, path,
    shading) or contains nested marked content.  A completely empty
    ``BDC …EMC`` pair is not real: nothing on the page corresponds to it, so a
    struct element referencing it holds a dangling reference.

    WHY THIS CHANGED
    ----------------
    This used to count ANY BDC carrying an /MCID, empty or not.  That is why
    _strip_phantom_mcids reported "removed 0 phantom MCID ref(s)" on files that
    validate.py was simultaneously failing for 2 phantom MCIDs — the fixer and
    the validator disagreed about what "present" means, and the validator's
    definition is the one that decides whether the file passes.

    DELIBERATELY NARROWER THAN validate.content_mcids
    -------------------------------------------------
    That function attributes paint to the INNERMOST live MCID only, so an outer
    container MCID wrapping painting children reads as inkless there.  Removing
    such a reference would detach real content from the tree, so a sequence
    containing nested marked content is treated as real here even though
    validate.py would not count it.  Erring toward keeping a reference is
    recoverable; erring toward deleting one is not.
    """
    out = {}
    for pi, page in enumerate(pdf.pages):
        real: set = set()
        try:
            instrs = list(pikepdf.parse_content_stream(page))
        except Exception:
            out[pi] = real
            continue

        # one frame per open BDC/BMC level: {"mcid": int|None, "real": bool}
        stack: list = []
        for ins in instrs:
            try:
                o = str(ins.operator)
            except Exception:
                continue

            if o in ("BDC", "BMC"):
                mcid = None
                try:
                    ops = ins.operands
                    if o == "BDC" and len(ops) >= 2 \
                            and isinstance(ops[1], pikepdf.Dictionary) \
                            and "/MCID" in ops[1]:
                        mcid = int(ops[1]["/MCID"])
                except Exception:
                    mcid = None
                # opening a nested sequence makes every enclosing one real
                for frame in stack:
                    frame["real"] = True
                stack.append({"mcid": mcid, "real": False})

            elif o == "EMC":
                if stack:
                    frame = stack.pop()
                    if frame["mcid"] is not None and frame["real"]:
                        real.add(frame["mcid"])

            elif o in _PAINT_OPS:
                # paint marks every enclosing sequence, not only the innermost
                for frame in stack:
                    frame["real"] = True

        # Unbalanced stream: keep whatever is still open rather than risk
        # stripping a reference to content we merely failed to parse cleanly.
        for frame in stack:
            if frame["mcid"] is not None:
                real.add(frame["mcid"])

        out[pi] = real
    return out


def _page_index_of_obj(pdf, page_obj):
    if page_obj is None:
        return None
    try:
        og = page_obj.objgen
    except Exception:
        return None
    for i, p in enumerate(pdf.pages):
        if p.obj.objgen == og:
            return i
    return None


def _strip_phantom_mcids(pdf, st, result):
    """Drop MCID references that point at sequences no longer in the stream.

    A fixer that rewrites a content stream can leave an element pointing at an
    MCID it removed (e.g. a sequence whose remaining half held no text, so no
    BDC was emitted for it).  The element then references marked content that
    does not exist — a dangling reference that PAC reports under "Structure
    Elements".  This sweep removes such references wherever they occur, so no
    single fixer's bookkeeping slip can break the file.
    """
    present = _present_mcids(pdf)
    seen = set()

    def walk(node, pi_inherited):
        pg = node.get("/Pg")
        pi = _page_index_of_obj(pdf, pg) if pg is not None else pi_inherited

        k = node.get("/K")
        if k is not None:
            kids = list(k) if isinstance(k, pikepdf.Array) else [k]
            keep = []
            for c in kids:
                if isinstance(c, pikepdf.Dictionary):
                    keep.append(c)
                    continue
                try:
                    m = int(c)
                except Exception:
                    keep.append(c)
                    continue
                if pi is None or m in present.get(pi, set()):
                    keep.append(c)
                else:
                    result["phantom_mcids_removed"] += 1
            if len(keep) != len(kids):
                node["/K"] = pikepdf.Array(keep)

        for c in _kids(node):
            if isinstance(c, pikepdf.Dictionary) and "/S" in c:
                key = _og(c)
                if key is not None:
                    if key in seen:
                        continue
                    seen.add(key)
                walk(c, pi)

    walk(st, None)


def fix_struct_parents(in_path: str, out_path: str) -> dict:
    result = {"parents_fixed": 0, "elements_visited": 0,
              "top_level_fixed": 0, "already_correct": 0,
              "phantom_mcids_removed": 0}

    pdf = pikepdf.open(in_path)
    st = pdf.Root.get("/StructTreeRoot")
    if st is None:
        pdf.save(out_path)
        print("struct_parent_fixer: no StructTreeRoot; nothing to do")
        return result

    # sweep dangling MCID references first, then fix parent pointers
    _strip_phantom_mcids(pdf, st, result)

    seen = set()

    def repair(node, actual_parent):
        """Set /P of every structural child of `node` to `node` itself."""
        for child in _kids(node):
            if not isinstance(child, pikepdf.Dictionary):
                continue          # MCID int
            if "/S" not in child:
                continue          # MCR / OBJR dicts have no /S
            key = _og(child)
            if key is not None:
                if key in seen:   # guard against cycles / shared objects
                    continue
                seen.add(key)

            result["elements_visited"] += 1

            declared = child.get("/P")
            if _og(declared) != _og(node):
                child["/P"] = node
                result["parents_fixed"] += 1
            else:
                result["already_correct"] += 1

            repair(child, child)

    # Top-level elements: their parent is the StructTreeRoot itself.
    for child in _kids(st):
        if not isinstance(child, pikepdf.Dictionary) or "/S" not in child:
            continue
        key = _og(child)
        if key is not None:
            if key in seen:
                continue
            seen.add(key)
        result["elements_visited"] += 1
        declared = child.get("/P")
        if _og(declared) != _og(st):
            child["/P"] = st
            result["parents_fixed"] += 1
            result["top_level_fixed"] += 1
        else:
            result["already_correct"] += 1
        repair(child, child)

    pdf.save(out_path)
    print(f"struct_parent_fixer: visited {result['elements_visited']} element(s); "
          f"repaired {result['parents_fixed']} stale /P pointer(s) "
          f"({result['top_level_fixed']} at top level); "
          f"removed {result['phantom_mcids_removed']} phantom MCID ref(s); "
          f"{result['already_correct']} already correct")
    return result


def main(argv):
    if len(argv) < 3:
        print("Usage: struct_parent_fixer.py <in.pdf> <out.pdf>", file=sys.stderr)
        return 2
    try:
        res = fix_struct_parents(argv[1], argv[2])
        print(json.dumps(res))
        return 0
    except Exception as exc:
        import traceback
        print(f"struct_parent_fixer: FAILED: {exc}\n{traceback.format_exc()}",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
