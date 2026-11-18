"""
tagged_annotations_fixer.py
---------------------------
Fix "Tagged annotations - Failed" in Adobe Acrobat accessibility checker.

Acrobat's rule requires every visible annotation (except Popups) to be
ENROLLED in the structure tree: an <Annot> StructElem containing an OBJR
(object reference) kid, with the annotation carrying a matching
/StructParent key registered in the ParentTree.

Merely injecting /Contents (the old behaviour of this script) does NOT
satisfy the rule — /Contents provides the accessible description, the
OBJR enrollment provides the tagging.  This version does both:

  1. For each annotation missing /Contents, inject a description.
  2. For each non-Popup, non-hidden annotation missing /StructParent,
     create an <Annot> StructElem + OBJR, register it in the ParentTree,
     and bump /ParentTreeNextKey.

CLI usage:
    python tagged_annotations_fixer.py <input.pdf> <output.pdf>
"""

from __future__ import annotations

import json
import sys
from typing import Any, Optional

import pikepdf
from pikepdf import Array, Dictionary, Name, String

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Annotation flag bits (PDF 32000-1 12.5.3)
_FLAG_HIDDEN = 2
_FLAG_NOVIEW = 32


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _build_contents(ann: Any, subtype: str, page_num: int) -> str:
    """Best-effort accessible description for an annotation."""
    if subtype == "Link":
        a_obj = ann.get("/A")
        if a_obj is not None:
            try:
                s = str(a_obj.get("/S", "")).lstrip("/")
                if s == "URI":
                    uri = a_obj.get("/URI")
                    if uri:
                        return f"Link: {str(uri)}"
                elif s in ("GoTo", "GoToR"):
                    return f"Link to page {page_num + 1}"
                elif s == "Named":
                    n = a_obj.get("/N")
                    if n:
                        return f"Link: {str(n)}"
            except Exception:
                pass
        return f"Link on page {page_num + 1}"

    if subtype == "Widget":
        for key in ("/TU", "/T", "/TM"):
            v = ann.get(key)
            if v:
                return str(v).strip()
        return f"Form field on page {page_num + 1}"

    if subtype == "Popup":
        return "Popup annotation"

    return f"{subtype} annotation on page {page_num + 1}"


def _is_hidden(ann) -> bool:
    try:
        f = int(ann.get("/F", 0))
    except Exception:
        f = 0
    return bool(f & _FLAG_HIDDEN or f & _FLAG_NOVIEW)


def _find_document_element(struct_root) -> Optional[pikepdf.Dictionary]:
    """Return the top-level <Document> element (or first root child)."""
    k = struct_root.get("/K")
    if k is None:
        return None
    if isinstance(k, pikepdf.Array):
        for child in k:
            if isinstance(child, pikepdf.Dictionary):
                return child
        return None
    return k if isinstance(k, pikepdf.Dictionary) else None


def _parenttree_nums_node(node) -> Optional[pikepdf.Dictionary]:
    """Descend a number tree to the RIGHTMOST leaf that has /Nums."""
    if "/Nums" in node:
        return node
    kids = node.get("/Kids")
    if kids is not None and len(kids) > 0:
        return _parenttree_nums_node(kids[len(kids) - 1])
    return None


def _next_struct_parent_key(struct_root) -> int:
    """Return a safe next key for the ParentTree."""
    try:
        nk = struct_root.get("/ParentTreeNextKey")
        if nk is not None:
            return int(nk)
    except Exception:
        pass
    # Fallback: scan max key in the rightmost leaf
    pt = struct_root.get("/ParentTree")
    leaf = _parenttree_nums_node(pt) if pt is not None else None
    if leaf is not None and len(leaf["/Nums"]) >= 2:
        return int(leaf["/Nums"][len(leaf["/Nums"]) - 2]) + 1
    return 0


def _append_parenttree_entry(struct_root, key: int, value) -> bool:
    """Append key -> value at the end of the ParentTree number tree."""
    pt = struct_root.get("/ParentTree")
    if pt is None:
        return False
    leaf = _parenttree_nums_node(pt)
    if leaf is None:
        return False
    leaf["/Nums"].append(key)
    leaf["/Nums"].append(value)
    # Keep /Limits consistent on intermediate-tree leaves
    if "/Limits" in leaf:
        try:
            leaf["/Limits"][1] = key
        except Exception:
            pass
    return True


# ---------------------------------------------------------------------------
# main fix
# ---------------------------------------------------------------------------

def fix_tagged_annotations(input_path: str, output_path: str) -> dict:
    """
    Ensure every annotation has /Contents AND every visible non-Popup
    annotation is enrolled in the structure tree (Annot elem + OBJR +
    StructParent + ParentTree entry).  Returns dict with counts.
    """
    print(f"[ANN] input={input_path!r}")
    print(f"[ANN] output={output_path!r}")

    result: dict[str, Any] = {
        "annotations_found": 0,
        "contents_added": 0,
        "already_had_contents": 0,
        "enrolled": 0,
        "already_enrolled": 0,
        "skipped_popup_or_hidden": 0,
        "failed": 0,
        "details": [],
    }

    with pikepdf.open(input_path) as pdf:
        struct_root = pdf.Root.get("/StructTreeRoot")
        doc_elem = _find_document_element(struct_root) if struct_root is not None else None
        if struct_root is None:
            print("[ANN] WARNING: no StructTreeRoot — enrollment not possible")
        elif doc_elem is None:
            doc_elem = struct_root
            print("[ANN] WARNING: no Document element — attaching Annot elems to StructTreeRoot")

        next_key = _next_struct_parent_key(struct_root) if struct_root is not None else 0

        for page_num, page in enumerate(pdf.pages):
            annots = page.get("/Annots")
            if annots is None:
                continue
            for ann in annots:
                try:
                    if not isinstance(ann, pikepdf.Dictionary):
                        continue
                    result["annotations_found"] += 1
                    subtype = str(ann.get("/Subtype", "")).lstrip("/")

                    # ── 1. accessible description ────────────────────────
                    existing = ann.get("/Contents")
                    if existing is not None and str(existing).strip():
                        result["already_had_contents"] += 1
                        contents_text = str(existing)
                    else:
                        contents_text = _build_contents(ann, subtype, page_num)
                        ann["/Contents"] = String(contents_text)
                        result["contents_added"] += 1
                        print(f"[ANN] page {page_num + 1} {subtype}: "
                              f"set /Contents={contents_text[:60]!r}")

                    # ── 2. structure-tree enrollment ─────────────────────
                    if subtype == "Popup" or _is_hidden(ann):
                        result["skipped_popup_or_hidden"] += 1
                        continue
                    if struct_root is None:
                        continue
                    if "/StructParent" in ann:
                        result["already_enrolled"] += 1
                        continue

                    sp_key = next_key
                    objr = pdf.make_indirect(Dictionary(
                        Type=Name("/OBJR"),
                        Obj=ann,
                        Pg=page.obj,
                    ))
                    elem = pdf.make_indirect(Dictionary(
                        Type=Name("/StructElem"),
                        S=Name("/Annot"),
                        P=doc_elem,
                        Pg=page.obj,
                        K=Array([objr]),
                        Alt=String(contents_text),
                    ))

                    # attach to the Document element's kids
                    dk = doc_elem.get("/K")
                    if dk is None:
                        doc_elem["/K"] = Array([elem])
                    elif isinstance(dk, pikepdf.Array):
                        dk.append(elem)
                    else:
                        doc_elem["/K"] = Array([dk, elem])

                    if not _append_parenttree_entry(struct_root, sp_key, elem):
                        print(f"[ANN] page {page_num + 1} {subtype}: "
                              f"ParentTree append FAILED — rolling back elem")
                        result["failed"] += 1
                        continue

                    ann["/StructParent"] = sp_key
                    next_key += 1
                    struct_root["/ParentTreeNextKey"] = next_key
                    result["enrolled"] += 1
                    result["details"].append({
                        "page": page_num + 1, "subtype": subtype,
                        "struct_parent": sp_key,
                    })
                    print(f"[ANN] page {page_num + 1} {subtype}: "
                          f"enrolled in struct tree (StructParent={sp_key})")

                except Exception as e:
                    print(f"[ANN] page {page_num + 1}: error: {e}")
                    result["failed"] += 1

        pdf.save(output_path)

    print(f"[ANN] done: found={result['annotations_found']} "
          f"contents_added={result['contents_added']} "
          f"enrolled={result['enrolled']} "
          f"already_enrolled={result['already_enrolled']} "
          f"failed={result['failed']}")
    print(f"[ANN] saved -> {output_path}")
    return result


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: tagged_annotations_fixer.py <input.pdf> <output.pdf>")
        sys.exit(1)
    res = fix_tagged_annotations(sys.argv[1], sys.argv[2])
    print(json.dumps(res, indent=2))
