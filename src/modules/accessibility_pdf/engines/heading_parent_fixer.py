"""
heading_parent_fixer.py
-----------------------
Detect and fix heading structure elements (H1-H6) that have invalid
parent element types in the PDF structure tree.

PAC Matterhorn Protocol fires "Invalid use of an H1 structure element"
when an H1-H6 element is a direct child of an element that is NOT a
valid grouping container (e.g. /P, /TD, /TH, /Figure, /Span).

Valid parent types per PDF/UA 6.4.2:
    /Document  /Part  /Art  /Sect  /Div  /BlockQuote  /Caption
    /TOC  /TOCI  /Index  /Private

Fix strategy: for each misplaced heading, walk up the tree via /P
pointers until a valid ancestor is found, then re-parent the heading
element there — removing it from the bad parent's /K, appending it to
the valid ancestor's /K, and updating the heading's /P pointer.

Public API:
    find_invalid_heading_parents(pdf_path) -> list[dict]
    fix_invalid_heading_parents(pdf_path)  -> dict  {fixed, skipped}
"""
from __future__ import annotations
import logging

log = logging.getLogger(__name__)

# "/Title" is included because it role-maps to /H1 (see title_tag.py) and is
# therefore subject to the same PDF/UA 6.4.2 parent-type restriction as a
# heading: a <Title> sitting inside a /TD or /Figure is just as invalid.
_HEADING_TAGS: set[str] = {"/H", "/H1", "/H2", "/H3", "/H4", "/H5", "/H6", "/Title"}

# PDF/UA 6.4.2 — valid parent element types for heading (H / Hn) elements.
_VALID_HEADING_PARENTS: set[str] = {
    "/Document", "/Sect", "/Part", "/Art", "/Div",
    "/BlockQuote", "/Caption", "/TOC", "/TOCI",
    "/Index", "/Private",
}


# ---------------------------------------------------------------------------
# internal helpers
# ---------------------------------------------------------------------------

def _get_parent_type(elem, default: str = "") -> str:
    """Return the /S type string of elem's /P parent, or *default*."""
    try:
        import pikepdf
        p_ref = elem.get("/P")
        if p_ref is None:
            return default
        p_obj = p_ref.get_object() if hasattr(p_ref, "get_object") else p_ref
        if isinstance(p_obj, pikepdf.Dictionary):
            return str(p_obj.get("/S", default))
    except Exception:
        pass
    return default


def _same_object(a, b) -> bool:
    """True if two pikepdf objects reference the same underlying PDF object."""
    try:
        return a.objgen == b.objgen
    except AttributeError:
        return a is b


def _walk(struct_root, visitor) -> None:
    """Call visitor(node) for every pikepdf.Dictionary node in the struct tree."""
    import pikepdf

    def _recurse(node):
        try:
            if not isinstance(node, pikepdf.Dictionary):
                return
            visitor(node)
            k = node.get("/K")
            if k is None:
                return
            if isinstance(k, pikepdf.Array):
                for child in k:
                    try:
                        obj = (child if isinstance(child, pikepdf.Dictionary)
                               else child.get_object())
                        _recurse(obj)
                    except Exception:
                        pass
            elif isinstance(k, pikepdf.Dictionary):
                _recurse(k)
        except Exception:
            pass

    k_root = struct_root.get("/K")
    if isinstance(k_root, pikepdf.Array):
        for child in k_root:
            try:
                obj = (child if isinstance(child, pikepdf.Dictionary)
                       else child.get_object())
                _recurse(obj)
            except Exception:
                pass
    elif isinstance(k_root, pikepdf.Dictionary):
        _recurse(k_root)


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def find_invalid_heading_parents(pdf_path: str) -> list[dict]:
    """
    Walk the StructTree and return one dict per H1-H6 element whose parent
    element type is not in _VALID_HEADING_PARENTS.

    Each dict has keys:
        heading_tag  : str   (e.g. '/H1')
        parent_type  : str   (e.g. '/P', '/TD')
        page         : int|None  (1-based page number)
        description  : str
    """
    try:
        import pikepdf
    except ImportError:
        log.warning("find_invalid_heading_parents: pikepdf not available")
        return []

    issues: list[dict] = []

    try:
        with pikepdf.open(pdf_path) as pdf:
            struct_root = pdf.Root.get("/StructTreeRoot")
            if struct_root is None:
                return []

            # Build objgen → 1-based page number map
            page_idx: dict[tuple, int] = {}
            for i, page in enumerate(pdf.pages):
                try:
                    page_idx[page.obj.objgen] = i + 1
                except Exception:
                    pass

            def _visit(node):
                tag = str(node.get("/S", ""))
                if tag not in _HEADING_TAGS:
                    return
                pt = _get_parent_type(node)
                if not pt or pt in _VALID_HEADING_PARENTS:
                    return

                # Determine page number
                page_no: int | None = None
                pg_ref = node.get("/Pg")
                if pg_ref is not None:
                    try:
                        page_no = page_idx.get(pg_ref.objgen)
                    except Exception:
                        pass

                issues.append({
                    "heading_tag": tag,
                    "parent_type": pt,
                    "page":        page_no,
                    "description": (
                        f"{tag} element has invalid parent type '{pt}'"
                        f" (page {page_no})"
                        " — PAC Matterhorn 'Invalid use of Hn structure element'"
                    ),
                })

            _walk(struct_root, _visit)

    except Exception as exc:
        log.error("find_invalid_heading_parents: %s", exc)

    return issues


def fix_invalid_heading_parents(pdf_path: str) -> dict:
    """
    For each H1-H6 element with an invalid parent type, re-parent it to the
    nearest valid ancestor found by walking up the /P chain.

    Steps per heading element:
      1. Identify bad_parent (current invalid parent).
      2. Walk up /P chain until a node whose /S is in _VALID_HEADING_PARENTS
         (or has no /S — i.e. the StructTreeRoot) is found → valid_ancestor.
      3. Remove heading from bad_parent /K.
      4. Append heading to valid_ancestor /K.
      5. Update heading /P to valid_ancestor.
      6. Save once if any changes were made.

    Returns {'fixed': int, 'skipped': int}.
    """
    try:
        import pikepdf
        from pikepdf import Array
    except ImportError:
        log.warning("fix_invalid_heading_parents: pikepdf not available")
        return {"fixed": 0, "skipped": 0, "error": "pikepdf not available"}

    fixed = 0
    skipped = 0

    try:
        with pikepdf.open(pdf_path, allow_overwriting_input=True) as pdf:
            struct_root = pdf.Root.get("/StructTreeRoot")
            if struct_root is None:
                return {"fixed": 0, "skipped": 0}

            # ── Collect misplaced (heading, bad_parent) pairs ────────────────
            misplaced: list[tuple] = []

            def _collect(node):
                tag = str(node.get("/S", ""))
                if tag not in _HEADING_TAGS:
                    return
                pt = _get_parent_type(node)
                if not pt or pt in _VALID_HEADING_PARENTS:
                    return
                p_ref = node.get("/P")
                if p_ref is None:
                    return
                p_obj = p_ref.get_object() if hasattr(p_ref, "get_object") else p_ref
                if isinstance(p_obj, pikepdf.Dictionary):
                    misplaced.append((node, p_obj))

            _walk(struct_root, _collect)

            if not misplaced:
                return {"fixed": 0, "skipped": 0}

            # ── Fix each misplaced heading ───────────────────────────────────
            for heading_obj, bad_parent in misplaced:
                try:
                    heading_tag = str(heading_obj.get("/S", "?"))
                    bad_type    = str(bad_parent.get("/S", "?"))

                    # Step 1 — find nearest valid ancestor
                    valid_ancestor = None
                    current = bad_parent
                    for _ in range(20):          # guard against cycles
                        p_ref = current.get("/P")
                        if p_ref is None:
                            break
                        p_obj = (p_ref.get_object()
                                 if hasattr(p_ref, "get_object") else p_ref)
                        if not isinstance(p_obj, pikepdf.Dictionary):
                            break
                        p_type = str(p_obj.get("/S", ""))
                        # Empty /S → StructTreeRoot level, treat as Document
                        if not p_type or p_type in _VALID_HEADING_PARENTS:
                            valid_ancestor = p_obj
                            break
                        current = p_obj

                    if valid_ancestor is None:
                        log.warning(
                            "fix_invalid_heading_parents: no valid ancestor "
                            "for %s (parent=%s) — skipping",
                            heading_tag, bad_type,
                        )
                        skipped += 1
                        continue

                    anc_type = str(valid_ancestor.get("/S", "(StructTreeRoot)"))

                    # Step 2 — remove heading from bad_parent /K
                    bad_k = bad_parent.get("/K")
                    if isinstance(bad_k, pikepdf.Array):
                        remaining = []
                        for item in bad_k:
                            try:
                                item_obj = (item if isinstance(item, pikepdf.Dictionary)
                                            else item.get_object())
                                if not _same_object(item_obj, heading_obj):
                                    remaining.append(item)
                            except Exception:
                                remaining.append(item)
                        bad_parent["/K"] = Array(remaining)
                    elif isinstance(bad_k, pikepdf.Dictionary):
                        if _same_object(bad_k, heading_obj):
                            bad_parent["/K"] = Array([])

                    # Step 3 — splice heading into valid_ancestor /K *in place*.
                    #
                    # It must go NEXT TO the sub-tree it came out of, not at the
                    # end of the ancestor's kid list: appending moves the heading
                    # to the bottom of the section in the reading order a screen
                    # reader follows, which is a worse defect than the one being
                    # fixed. Find the ancestor's direct child that (transitively)
                    # contained the heading and insert immediately after it.
                    anc_k = valid_ancestor.get("/K")
                    if anc_k is None:
                        valid_ancestor["/K"] = Array([heading_obj])
                    elif isinstance(anc_k, pikepdf.Array):
                        # which direct child of valid_ancestor is on the /P chain?
                        chain_child = bad_parent
                        cur_c = bad_parent
                        for _ in range(20):
                            p_ref = cur_c.get("/P")
                            if p_ref is None:
                                break
                            p_obj = (p_ref.get_object()
                                     if hasattr(p_ref, "get_object") else p_ref)
                            if not isinstance(p_obj, pikepdf.Dictionary):
                                break
                            if _same_object(p_obj, valid_ancestor):
                                chain_child = cur_c
                                break
                            cur_c = p_obj

                        items = list(anc_k)
                        insert_at = len(items)
                        for _i, _it in enumerate(items):
                            try:
                                _it_obj = (_it if isinstance(_it, pikepdf.Dictionary)
                                           else _it.get_object())
                                if _same_object(_it_obj, chain_child):
                                    insert_at = _i + 1
                                    break
                            except Exception:
                                continue
                        items.insert(insert_at, heading_obj)
                        valid_ancestor["/K"] = Array(items)
                    else:
                        # Integer (MCID) or single dict — promote to array
                        valid_ancestor["/K"] = Array([anc_k, heading_obj])

                    # Step 4 — update heading's /P pointer
                    heading_obj["/P"] = valid_ancestor

                    log.info(
                        "fix_invalid_heading_parents: %s re-parented  %s → %s",
                        heading_tag, bad_type, anc_type,
                    )
                    fixed += 1

                except Exception as item_err:
                    log.warning(
                        "fix_invalid_heading_parents item error: %s", item_err
                    )
                    skipped += 1

            if fixed:
                pdf.save(pdf_path)

    except Exception as exc:
        log.error("fix_invalid_heading_parents: %s", exc, exc_info=True)
        return {"fixed": 0, "skipped": skipped, "error": str(exc)}

    log.info(
        "fix_invalid_heading_parents: fixed=%d skipped=%d", fixed, skipped
    )
    return {"fixed": fixed, "skipped": skipped}
