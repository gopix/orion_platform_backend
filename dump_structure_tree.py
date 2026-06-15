"""Diagnostic helper to dump PDF structure tree node types.

Run independently for a single PDF file.
Example:
    python dump_structure_tree.py C:/path/to/file.pdf
"""

from __future__ import annotations

import argparse
from pathlib import Path

from pdfixsdk.Pdfix import GetPdfix, PdfTagsParams


def safe_call(obj, method_name, *args):
    if not hasattr(obj, method_name):
        return False, f"N/A (method not found: {method_name})"

    method = getattr(obj, method_name)
    try:
        return True, method(*args)
    except TypeError as exc:
        return False, f"TypeError: {exc}"
    except Exception as exc:
        return False, f"Error: {exc}"


def get_node_type(node):
    for method_name in ("GetType", "GetTagName"):
        ok, value = safe_call(node, method_name, True)
        if ok:
            return value

        ok, value = safe_call(node, method_name, False)
        if ok:
            return value

        ok, value = safe_call(node, method_name)
        if ok:
            return value

    return "UNKNOWN"


def get_child(node, index):
    if hasattr(node, "GetChildObject"):
        ok, child = safe_call(node, "GetChildObject", index)
        if ok:
            return child

    if hasattr(node, "GetChild"):
        ok, child = safe_call(node, "GetChild", index)
        if ok:
            return child

    return None


def resolve_struct_element(node, struct_tree):
    if node is None:
        return None
    if hasattr(node, "GetType"):
        return node
    if struct_tree is not None and hasattr(struct_tree, "GetStructElementFromObject"):
        ok, resolved = safe_call(struct_tree, "GetStructElementFromObject", node)
        if ok and resolved is not None:
            return resolved
    return node


def traverse_structure_tree(node, struct_tree=None, depth=0, prefix=""):
    node = resolve_struct_element(node, struct_tree)
    node_type = get_node_type(node)
    indent = "  " * depth

    types = []
    if node_type != "UNKNOWN":
        print(f"{indent}{prefix}{node_type}")
        types.append(node_type)

    ok, child_count = safe_call(node, "GetNumChildren")
    if not ok or not isinstance(child_count, int):
        return types

    for child_index in range(child_count):
        child = get_child(node, child_index)
        if not child:
            continue

        types.extend(traverse_structure_tree(child, struct_tree=struct_tree, depth=depth + 1, prefix=f"[{child_index}] "))

    return types


def dump_structure_tree(pdf_doc):
    struct_tree = pdf_doc.GetStructTree()
    if not struct_tree:
        print("No structure tree found. The PDF may not be tagged.")
        return

    print("PDF structure tree order:")

    types = []
    ok, num_children = safe_call(struct_tree, "GetNumChildren")
    if not ok or not isinstance(num_children, int):
        print("Unable to inspect structure tree children.")
        return

    for i in range(num_children):
        child_obj = get_child(struct_tree, i)
        if not child_obj:
            continue
        types.extend(traverse_structure_tree(child_obj, struct_tree=struct_tree, depth=0))

    unique_types = sorted({str(t) for t in types if t != "UNKNOWN"})
    print("\nUnique node types found:")
    for node_type in unique_types:
        print(node_type)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Dump PDF structure tree node types.")
    parser.add_argument("pdf_path", type=Path, help="Path to the PDF file to inspect")
    args = parser.parse_args(argv)

    pdf_path = args.pdf_path
    if not pdf_path.exists() or not pdf_path.is_file():
        print(f"PDF file not found: {pdf_path}")
        return 1

    pdfix = GetPdfix()
    if not pdfix:
        print("Failed to initialize PDFix.")
        return 1

    pdf_doc = pdfix.OpenDoc(str(pdf_path), "")
    if not pdf_doc:
        print(f"Failed to open PDF file: {pdf_path}")
        return 1

    try:
        dump_structure_tree(pdf_doc)
    finally:
        pdf_doc.Close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
