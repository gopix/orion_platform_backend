"""
tagged_annotations_fixer.py
---------------------------
Fix "Tagged annotations - Failed" in Adobe Acrobat accessibility checker.

Strategy:
  1. Use PdfReader to find ALL annotations on all pages (more reliable than PdfWriter).
  2. For each annotation missing /Contents, inject a description.
  3. Also scan the structure tree for OBJR (Object Reference) kids which point to
     annotation objects that must be tagged.
  4. Write the patched PDF via PdfWriter cloned from the original.

CLI usage:
    python tagged_annotations_fixer.py <input.pdf> <output.pdf>
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, TextStringObject

import sys as _sys
if hasattr(_sys.stdout, "reconfigure"):
    try:
        _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def fix_tagged_annotations(input_path: str, output_path: str) -> dict:
    """
    Find all annotations and ensure each has /Contents for accessibility.
    Returns dict with counts.
    """
    print(f"[ANN] input={input_path!r}")
    print(f"[ANN] output={output_path!r}")

    result: dict[str, Any] = {
        "annotations_found": 0,
        "contents_added": 0,
        "already_had_contents": 0,
        "failed": 0,
        "details": [],
    }

    # Use PdfReader first to discover all annotations
    reader = PdfReader(str(input_path))
    ann_pages: dict[int, list] = {}  # page_num -> list of (idnum, gen, subtype, has_contents)

    for page_num, page in enumerate(reader.pages):
        raw = page.get("/Annots")
        if raw is None:
            continue
        try:
            annots = raw.get_object()
        except Exception as e:
            print(f"[ANN] page {page_num}: cannot resolve /Annots: {e}")
            continue
        if not hasattr(annots, "__iter__"):
            continue

        page_anns = []
        for item in annots:
            try:
                ann = item.get_object()
                if not hasattr(ann, "get"):
                    continue
                subtype = str(ann.get("/Subtype", "")).lstrip("/")
                has_cont = bool(ann.get("/Contents"))
                ref = getattr(item, "idnum", None)
                gen = getattr(item, "generation", 0)
                page_anns.append((ref, gen, subtype, has_cont, ann))
                print(f"[ANN] page {page_num}: found {subtype} ref={ref} has_contents={has_cont}")
            except Exception as e:
                print(f"[ANN] page {page_num}: item error: {e}")
        if page_anns:
            ann_pages[page_num] = page_anns

    # Also scan structure tree for OBJR kids (annotations referenced in tag tree)
    root = reader.trailer.get("/Root", {})
    if hasattr(root, "get_object"):
        root = root.get_object()
    struct_root = root.get("/StructTreeRoot") if hasattr(root, "get") else None
    if struct_root:
        try:
            struct_root = struct_root.get_object()
            _scan_struct_for_objr(struct_root, reader, result, set())
        except Exception as e:
            print(f"[ANN] struct scan error: {e}")

    total_found = sum(len(v) for v in ann_pages.values())
    print(f"[ANN] total page annotations found via PdfReader: {total_found}")
    result["annotations_found"] = total_found

    if total_found == 0 and result.get("_objr_found", 0) == 0:
        print("[ANN] no annotations found -- nothing to patch")
        # Still write the output (identity copy)
        writer = PdfWriter(clone_from=str(input_path))
        with open(output_path, "wb") as fh:
            writer.write(fh)
        print(f"[ANN] saved (no changes) -> {output_path}")
        return result

    # Now patch using PdfWriter
    writer = PdfWriter(clone_from=str(input_path))

    for page_num, page in enumerate(writer.pages):
        raw = page.get("/Annots")
        if raw is None:
            continue
        try:
            annots = raw.get_object()
        except Exception:
            continue
        if not hasattr(annots, "__iter__"):
            continue

        for item in list(annots):
            try:
                ann = item.get_object()
                if not hasattr(ann, "get"):
                    continue
                subtype = str(ann.get("/Subtype", "")).lstrip("/")
                existing = ann.get("/Contents")
                if existing and str(existing).strip():
                    result["already_had_contents"] += 1
                    continue
                contents_text = _build_contents(ann, subtype, page_num)
                ann[NameObject("/Contents")] = TextStringObject(contents_text)
                result["contents_added"] += 1
                result["details"].append({"page": page_num, "subtype": subtype, "contents": contents_text})
                print(f"[ANN] page {page_num} {subtype}: set /Contents={repr(contents_text)[:60]}")
            except Exception as e:
                print(f"[ANN] page {page_num}: patch error: {e}")
                result["failed"] += 1

    with open(output_path, "wb") as fh:
        writer.write(fh)

    print(f"[ANN] done: found={result['annotations_found']} added={result['contents_added']} "
          f"skipped={result['already_had_contents']} failed={result['failed']}")
    print(f"[ANN] saved -> {output_path}")
    return result


def _scan_struct_for_objr(obj, reader, result, seen):
    """Recursively scan structure tree for OBJR (Object Reference) kids."""
    try:
        obj = obj.get_object()
    except Exception:
        return
    oid = id(obj)
    if oid in seen:
        return
    seen.add(oid)
    if not hasattr(obj, "get"):
        return

    type_val = str(obj.get("/Type", "")).lstrip("/")
    if type_val == "OBJR":
        # This is an annotation reference in the structure tree
        ref = obj.get("/Obj")
        if ref:
            try:
                ann = ref.get_object()
                subtype = str(ann.get("/Subtype", "?")).lstrip("/")
                has_cont = bool(ann.get("/Contents"))
                print(f"[ANN] OBJR in struct tree: subtype={subtype} has_contents={has_cont}")
                result["_objr_found"] = result.get("_objr_found", 0) + 1
                result["annotations_found"] = result.get("annotations_found", 0) + 1
            except Exception as e:
                print(f"[ANN] OBJR resolve error: {e}")
        return

    kids = obj.get("/K")
    if kids is None:
        return
    try:
        kids = kids.get_object()
    except Exception:
        return
    if hasattr(kids, "get"):
        _scan_struct_for_objr(kids, reader, result, seen)
    elif hasattr(kids, "__iter__") and not isinstance(kids, (str, bytes)):
        for kid in kids:
            _scan_struct_for_objr(kid, reader, result, seen)


def _build_contents(ann: Any, subtype: str, page_num: int) -> str:
    if subtype == "Link":
        a_obj = ann.get("/A")
        if a_obj:
            try:
                a = a_obj.get_object()
                s = str(a.get("/S", "")).lstrip("/")
                if s == "URI":
                    uri = a.get("/URI")
                    if uri:
                        return f"Link: {str(uri)}"
                elif s in ("GoTo", "GoToR"):
                    return f"Link to page {page_num + 1}"
                elif s == "Named":
                    n = a.get("/N")
                    if n:
                        return f"Link: {str(n)}"
            except Exception:
                pass
        return f"Link on page {page_num + 1}"

    if subtype == "Widget":
        for key in ("/T", "/TU", "/TM"):
            v = ann.get(key)
            if v:
                return str(v).strip()
        return f"Form field on page {page_num + 1}"

    if subtype == "Popup":
        return "Popup annotation"

    return f"{subtype} annotation on page {page_num + 1}"


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: tagged_annotations_fixer.py <input.pdf> <output.pdf>")
        sys.exit(1)
    res = fix_tagged_annotations(sys.argv[1], sys.argv[2])
    print(json.dumps(res, indent=2))
