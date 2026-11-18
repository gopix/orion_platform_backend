"""
review_comment_remover.py
-------------------------
Remove review/markup annotations (proofreader comments) from a PDF before
accessibility remediation.

Editorial comments — sticky notes ("why blank?"), ink circles, carets,
strike-outs and their popup partners — are production leftovers that should
never ship in a published, accessible document.  Tagging them would make
them screen-reader-visible; leaving them untagged fails Acrobat's
"Tagged annotations" rule.  Removing them is the correct remediation.

Also cleans up the structure tree so nothing dangles:
  * <Annot> StructElems whose OBJR points at a removed annotation are
    detached from their parent's /K
  * ParentTree entries keyed by the removed annotations' /StructParent
    values are dropped

Kept by default: Link, Widget, Screen, PrinterMark, TrapNet, Watermark, 3D.

CLI usage:
    python review_comment_remover.py <input.pdf> <output.pdf>
"""

from __future__ import annotations

import json
import sys
from typing import Any

import pikepdf
from pikepdf import Array

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Markup / review annotation subtypes to strip
REVIEW_SUBTYPES = {
    "/Text", "/FreeText", "/Ink", "/Caret", "/StrikeOut", "/Highlight",
    "/Underline", "/Squiggly", "/Popup", "/Line", "/Square", "/Circle",
    "/Polygon", "/PolyLine", "/Stamp", "/Sound", "/FileAttachment",
}


def remove_review_comments(input_path: str, output_path: str) -> dict:
    """Strip review markup annotations and their structure-tree references."""
    print(f"[CMT] input={input_path!r}")
    print(f"[CMT] output={output_path!r}")

    result: dict[str, Any] = {"removed": 0, "kept": 0,
                              "struct_elems_detached": 0,
                              "parenttree_keys_dropped": 0,
                              "by_subtype": {}}

    with pikepdf.open(input_path) as pdf:
        removed_objgens: set = set()
        removed_sp_keys: set = set()

        # ── 1. filter page /Annots ────────────────────────────────────
        for page in pdf.pages:
            annots = page.get("/Annots")
            if annots is None:
                continue
            keep = []
            for ann in annots:
                try:
                    subtype = str(ann.get("/Subtype", ""))
                except Exception:
                    subtype = ""
                if subtype in REVIEW_SUBTYPES:
                    result["removed"] += 1
                    result["by_subtype"][subtype] = \
                        result["by_subtype"].get(subtype, 0) + 1
                    try:
                        if ann.is_indirect:
                            removed_objgens.add(ann.objgen)
                        sp = ann.get("/StructParent")
                        if sp is not None:
                            removed_sp_keys.add(int(sp))
                    except Exception:
                        pass
                else:
                    result["kept"] += 1
                    keep.append(ann)
            if keep:
                page["/Annots"] = Array(keep)
            else:
                del page["/Annots"]

        # ── 2. detach <Annot> StructElems whose OBJR points at a removed
        #       annotation ────────────────────────────────────────────
        struct_root = pdf.Root.get("/StructTreeRoot")

        def _objr_points_removed(node) -> bool:
            try:
                if str(node.get("/Type", "")) != "/OBJR":
                    return False
                obj = node.get("/Obj")
                return (obj is not None and obj.is_indirect
                        and obj.objgen in removed_objgens)
            except Exception:
                return False

        def _clean(node, seen) -> None:
            if not isinstance(node, pikepdf.Dictionary):
                return
            try:
                key = node.objgen if node.is_indirect else id(node)
            except Exception:
                key = id(node)
            if key in seen:
                return
            seen.add(key)

            k = node.get("/K")
            if k is None:
                return
            if isinstance(k, pikepdf.Array):
                keep_kids = []
                changed = False
                for kid in k:
                    if isinstance(kid, pikepdf.Dictionary):
                        if _objr_points_removed(kid):
                            changed = True
                            result["struct_elems_detached"] += 1
                            continue
                        # <Annot> elem whose ONLY kid is a removed OBJR
                        kk = kid.get("/K")
                        if kk is not None and isinstance(kk, pikepdf.Dictionary) \
                                and _objr_points_removed(kk):
                            changed = True
                            result["struct_elems_detached"] += 1
                            continue
                        if kk is not None and isinstance(kk, pikepdf.Array):
                            inner = [c for c in kk
                                     if not (isinstance(c, pikepdf.Dictionary)
                                             and _objr_points_removed(c))]
                            if len(inner) != len(kk):
                                if inner:
                                    kid["/K"] = Array(inner)
                                else:
                                    changed = True
                                    result["struct_elems_detached"] += 1
                                    continue
                        _clean(kid, seen)
                    keep_kids.append(kid)
                if changed:
                    node["/K"] = Array(keep_kids)
            elif isinstance(k, pikepdf.Dictionary):
                if _objr_points_removed(k):
                    del node["/K"]
                    result["struct_elems_detached"] += 1
                else:
                    _clean(k, seen)

        def _retag_objrless_annot_elems(node, seen) -> None:
            """
            <Annot> StructElems left WITHOUT an OBJR kid (their annotation
            was removed) but still holding real text MCIDs: retag to <Span>
            so the marked content stays in the tree with a neutral role.
            """
            if not isinstance(node, pikepdf.Dictionary):
                return
            try:
                key = node.objgen if node.is_indirect else id(node)
            except Exception:
                key = id(node)
            if key in seen:
                return
            seen.add(key)
            if str(node.get("/S", "")) == "/Annot":
                k = node.get("/K")
                kids = (list(k) if isinstance(k, pikepdf.Array)
                        else [k] if k is not None else [])
                has_objr = any(isinstance(c, pikepdf.Dictionary)
                               and str(c.get("/Type", "")) == "/OBJR"
                               for c in kids)
                if not has_objr:
                    node["/S"] = pikepdf.Name("/Span")
                    result["annot_elems_retagged_span"] = \
                        result.get("annot_elems_retagged_span", 0) + 1
            k = node.get("/K")
            if k is None:
                return
            kids = list(k) if isinstance(k, pikepdf.Array) else [k]
            for kid in kids:
                if isinstance(kid, pikepdf.Dictionary):
                    _retag_objrless_annot_elems(kid, seen)

        if struct_root is not None and removed_objgens:
            _clean(struct_root, set())
            _retag_objrless_annot_elems(struct_root, set())

            # ── 3. drop ParentTree entries for removed annotations ────
            def _prune_numtree(node) -> None:
                if "/Nums" in node:
                    nums = node["/Nums"]
                    new_nums = []
                    for i in range(0, len(nums) - 1, 2):
                        key_i, val = int(nums[i]), nums[i + 1]
                        drop = key_i in removed_sp_keys
                        if not drop and isinstance(val, pikepdf.Dictionary):
                            # value may be an <Annot> elem with removed OBJR
                            kk = val.get("/K")
                            if kk is not None and isinstance(kk, pikepdf.Dictionary) \
                                    and _objr_points_removed(kk):
                                drop = True
                        if drop:
                            result["parenttree_keys_dropped"] += 1
                        else:
                            new_nums.append(nums[i])
                            new_nums.append(val)
                    node["/Nums"] = Array(new_nums)
                kids = node.get("/Kids")
                if kids is not None:
                    for kid in kids:
                        _prune_numtree(kid)

            pt = struct_root.get("/ParentTree")
            if pt is not None and removed_sp_keys:
                _prune_numtree(pt)

        pdf.save(output_path)

    print(f"[CMT] done: removed={result['removed']} kept={result['kept']} "
          f"elems_detached={result['struct_elems_detached']} "
          f"pt_keys_dropped={result['parenttree_keys_dropped']}")
    print(f"[CMT] by_subtype={result['by_subtype']}")
    print(f"[CMT] saved -> {output_path}")
    return result


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: review_comment_remover.py <input.pdf> <output.pdf>")
        sys.exit(1)
    res = remove_review_comments(sys.argv[1], sys.argv[2])
    print(json.dumps(res, indent=2))
