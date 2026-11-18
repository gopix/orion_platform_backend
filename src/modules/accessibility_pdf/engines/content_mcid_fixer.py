"""
content_mcid_fixer.py
---------------------
Fix PAC hard-error "MCID N already present" caused by DUPLICATE MCIDs in
page CONTENT STREAMS.

PDFix AddTags() can emit colliding marked-content IDs inside one page,
e.g. both "/P <</MCID 1>> BDC" and "/Figure <</MCID 1>> BDC".  MCIDs must
be unique per page; PAC aborts the whole check when it meets the second
occurrence.  Adobe's checker does not detect this.

Strategy (per page):
  1. Find every inline "/Tag <</MCID n>> BDC" sequence in the page content
     stream(s), in stream order.
  2. Renumber them sequentially 0..N-1 and rewrite the stream.
  3. Re-point the structure tree at the new numbers: every reachable
     StructElem kid that claims (page, old_mcid) — integer kid or /MCR
     without /Stm — is matched to a content sequence by (tag == elem /S,
     old MCID, order) with an any-tag fallback, and updated.
  4. Rebuild the page's ParentTree array so slot[new_mcid] = owning elem.

Form XObjects with their own /StructParents keep their private MCID
namespace and are left untouched (as are /MCR kids carrying /Stm).

CLI usage:
    python content_mcid_fixer.py <input.pdf> <output.pdf>
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict, deque
from typing import Any, Optional

import pikepdf
from pikepdf import Array

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

_BDC_RE = re.compile(rb'/(\w+)\s*<<((?:[^<>]|<<[^<>]*>>)*?)>>\s*BDC')
_MCID_RE = re.compile(rb'(/MCID\s+)(\d+)')


def _page_content_bytes(page) -> bytes:
    c = page.get("/Contents")
    if c is None:
        return b""
    if isinstance(c, pikepdf.Array):
        return b"\n".join(s.read_bytes() for s in c)
    return c.read_bytes()


def fix_content_mcids(input_path: str, output_path: str) -> dict:
    print(f"[MCC] input={input_path!r}")
    print(f"[MCC] output={output_path!r}")

    result: dict[str, Any] = {
        "pages_with_duplicates": 0,
        "sequences_renumbered": 0,
        "tree_claims_updated": 0,
        "unmatched_tree_claims": 0,
        "page_arrays_rebuilt": 0,
    }

    with pikepdf.open(input_path) as pdf:
        struct_root = pdf.Root.get("/StructTreeRoot")

        # --------------------------------------------------------------
        # Collect reachable tree claims per page:
        # (page_objgen) -> [(elem, kid_locator, tag, old_mcid), ...]
        # kid_locator: ("int", index_in_K or None) | ("mcr", mcr_dict)
        # --------------------------------------------------------------
        page_claims: dict[Any, list] = defaultdict(list)
        parent_of: dict[Any, pikepdf.Dictionary] = {}
        seen: set = set()

        def _walk(node, inherited_pg):
            if not isinstance(node, pikepdf.Dictionary):
                return
            try:
                key = node.objgen if node.is_indirect else id(node)
            except Exception:
                key = id(node)
            if key in seen:
                return
            seen.add(key)
            pg = node.get("/Pg")
            pg_og = pg.objgen if (pg is not None and pg.is_indirect) else inherited_pg
            s = str(node.get("/S", "?")).lstrip("/")
            k = node.get("/K")
            if k is None:
                return
            if isinstance(k, pikepdf.Array):
                for idx in range(len(k)):
                    kid = k[idx]
                    _visit_kid(node, kid, idx, s, pg_og)
            else:
                _visit_kid(node, k, None, s, pg_og)

        def _visit_kid(elem, kid, idx, tag, pg_og):
            if isinstance(kid, pikepdf.Dictionary):
                t = str(kid.get("/Type", ""))
                if t == "/MCR":
                    if kid.get("/Stm") is not None:
                        return  # form-XObject namespace — leave alone
                    mpg = kid.get("/Pg")
                    mpg_og = mpg.objgen if (mpg is not None and mpg.is_indirect) else pg_og
                    try:
                        old = int(kid.get("/MCID"))
                    except Exception:
                        return
                    page_claims[mpg_og].append((elem, ("mcr", kid), tag, old))
                elif t != "/OBJR":
                    try:
                        parent_of[kid.objgen if kid.is_indirect else id(kid)] = elem
                    except Exception:
                        pass
                    _walk(kid, pg_og)
                return
            try:
                old = int(kid)
            except (TypeError, ValueError):
                return
            page_claims[pg_og].append((elem, ("int", idx), tag, old))

        if struct_root is not None:
            k_root = struct_root.get("/K")
            roots = list(k_root) if isinstance(k_root, pikepdf.Array) else [k_root]
            for child in roots:
                if isinstance(child, pikepdf.Dictionary):
                    _walk(child, None)

        # --------------------------------------------------------------
        # ParentTree access helpers
        # --------------------------------------------------------------
        def _set_parenttree_value(key: int, value) -> bool:
            pt = struct_root.get("/ParentTree") if struct_root is not None else None
            if pt is None:
                return False

            def _descend(node) -> bool:
                if "/Nums" in node:
                    nums = node["/Nums"]
                    for i in range(0, len(nums) - 1, 2):
                        if int(nums[i]) == key:
                            nums[i + 1] = value
                            return True
                for kid in (node.get("/Kids") or []):
                    if _descend(kid):
                        return True
                return False

            return _descend(pt)

        # --------------------------------------------------------------
        # Per page: renumber + re-point
        # --------------------------------------------------------------
        for pnum, page in enumerate(pdf.pages):
            data = _page_content_bytes(page)
            if not data:
                continue

            # gather sequences in stream order
            occurrences = []  # (span_of_number, tag, old)
            for m in _BDC_RE.finditer(data):
                props = m.group(2)
                mm = _MCID_RE.search(props)
                if mm is None:
                    continue
                num_start = m.start(2) + mm.start(2)
                num_end = m.start(2) + mm.end(2)
                occurrences.append(((num_start, num_end),
                                    m.group(1).decode("latin-1"),
                                    int(mm.group(2))))

            if not occurrences:
                continue
            olds = [o for _, _, o in occurrences]
            needs_renumber = len(set(olds)) != len(olds)

            if needs_renumber:
                result["pages_with_duplicates"] += 1
                # rewrite stream with sequential MCIDs
                new_data = bytearray()
                prev = 0
                for i, ((a, b), _tag, _old) in enumerate(occurrences):
                    new_data += data[prev:a]
                    new_data += str(i).encode("ascii")
                    prev = b
                new_data += data[prev:]
                page.Contents = pdf.make_stream(bytes(new_data))
                result["sequences_renumbered"] += len(occurrences)

            # matching structures
            by_tag_old: dict = defaultdict(deque)
            by_old: dict = defaultdict(deque)
            consumed = [False] * len(occurrences)
            for i, (_span, tag, old) in enumerate(occurrences):
                by_tag_old[(tag, old)].append(i)
                by_old[old].append(i)

            def _take(tag, old) -> Optional[int]:
                dq = by_tag_old.get((tag, old))
                while dq:
                    i = dq.popleft()
                    if not consumed[i]:
                        consumed[i] = True
                        return i
                dq = by_old.get(old)
                while dq:
                    i = dq.popleft()
                    if not consumed[i]:
                        consumed[i] = True
                        return i
                return None

            # update tree claims.  Unmatched claims are PHANTOMS — struct
            # elems referencing marked content that does not exist in the
            # stream (PDFix defect).  Their kids are pruned; elements left
            # empty are detached afterwards.
            pg_og = page.obj.objgen
            claims = page_claims.get(pg_og, [])
            new_page_array = [None] * len(occurrences)
            int_updates: dict = defaultdict(dict)   # elem_id -> {idx: new|None}
            elem_by_id: dict = {}
            mcr_removals: dict = defaultdict(list)  # elem_id -> [mcr objects]

            def _eid(el):
                try:
                    return el.objgen if el.is_indirect else id(el)
                except Exception:
                    return id(el)

            existing_olds = set(olds)
            for elem, locator, tag, old in claims:
                kind, ref = locator
                eid = _eid(elem)
                elem_by_id[eid] = elem
                if not needs_renumber:
                    # page content already unique: keep valid claims as-is,
                    # prune only PHANTOM claims (MCID absent from content)
                    if old in existing_olds:
                        continue
                    result["unmatched_tree_claims"] += 1
                    print(f"[MCC] page {pnum + 1}: phantom claim pruned "
                          f"tag={tag} old_mcid={old}")
                    if kind == "mcr":
                        mcr_removals[eid].append(ref)
                    else:
                        int_updates[eid][ref] = None
                    continue
                i = _take(tag, old)
                if i is None:
                    result["unmatched_tree_claims"] += 1
                    print(f"[MCC] page {pnum + 1}: phantom claim pruned "
                          f"tag={tag} old_mcid={old}")
                    if kind == "mcr":
                        mcr_removals[eid].append(ref)
                    else:
                        int_updates[eid][ref] = None
                    continue
                if kind == "mcr":
                    ref["/MCID"] = i
                else:
                    int_updates[eid][ref] = i
                new_page_array[i] = elem
                result["tree_claims_updated"] += 1

            # apply per-element /K rebuilds (int substitutions/removals and
            # phantom-MCR removals) in one pass to keep indices consistent
            for eid in set(list(int_updates.keys()) + list(mcr_removals.keys())):
                elem = elem_by_id[eid]
                k = elem.get("/K")
                if k is None:
                    continue
                if not isinstance(k, pikepdf.Array):
                    upd = int_updates.get(eid, {})
                    if None in upd or (upd and list(upd.values())[0] is None):
                        try:
                            del elem["/K"]
                        except Exception:
                            pass
                    elif upd:
                        elem["/K"] = list(upd.values())[0]
                    continue
                upd = int_updates.get(eid, {})
                drop_mcrs = mcr_removals.get(eid, [])
                new_kids = []
                for idx in range(len(k)):
                    kid = k[idx]
                    if idx in upd:
                        if upd[idx] is None:
                            continue  # phantom pruned
                        new_kids.append(upd[idx])
                        continue
                    if isinstance(kid, pikepdf.Dictionary):
                        dropped = False
                        for d in drop_mcrs:
                            try:
                                if (kid.is_indirect and d.is_indirect
                                        and kid.objgen == d.objgen) or kid is d:
                                    dropped = True
                                    break
                            except Exception:
                                pass
                        if dropped:
                            continue
                    new_kids.append(kid)
                if new_kids:
                    elem["/K"] = Array(new_kids)
                else:
                    try:
                        del elem["/K"]
                    except Exception:
                        pass
                    parent = parent_of.get(eid)
                    if parent is not None:
                        pk = parent.get("/K")
                        pkids = list(pk) if isinstance(pk, pikepdf.Array) else [pk]
                        kept = [c for c in pkids
                                if not (isinstance(c, pikepdf.Dictionary)
                                        and _eid(c) == eid)]
                        parent["/K"] = Array(kept)
                        result["phantom_elems_detached"] = \
                            result.get("phantom_elems_detached", 0) + 1

            # rebuild ParentTree page array (only when renumbered)
            sp = page.get("/StructParents")
            if needs_renumber and sp is not None and struct_root is not None:
                arr = Array()
                for el in new_page_array:
                    arr.append(el if el is not None else None)
                if _set_parenttree_value(int(sp), pdf.make_indirect(arr)):
                    result["page_arrays_rebuilt"] += 1

            if needs_renumber:
                print(f"[MCC] page {pnum + 1}: renumbered {len(occurrences)} "
                      f"sequences, updated {len(claims)} tree claims")

        pdf.save(output_path)

    print(f"[MCC] done: pages_fixed={result['pages_with_duplicates']} "
          f"sequences={result['sequences_renumbered']} "
          f"claims_updated={result['tree_claims_updated']} "
          f"unmatched={result['unmatched_tree_claims']}")
    print(f"[MCC] saved -> {output_path}")
    return result


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: content_mcid_fixer.py <input.pdf> <output.pdf>")
        sys.exit(1)
    res = fix_content_mcids(sys.argv[1], sys.argv[2])
    print(json.dumps(res, indent=2))
