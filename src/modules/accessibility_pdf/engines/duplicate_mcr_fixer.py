"""
duplicate_mcr_fixer.py
----------------------
Fix PAC hard-error "MCID N already present" (duplicate marked-content
references in the structure tree).

PDFix AddTags() sometimes emits multiple /MCR (marked-content reference)
kids pointing at the SAME (page, MCID) — both repeated inside one element
and spread across several placeholder <Figure> elements.  Adobe's checker
tolerates this; PAC 202x aborts the whole check with
"MCID N already present. The PDF document will be closed."

Strategy
  1. Collect every MCID claim in the reachable structure tree:
     (page, mcid) -> [(elem, kid), ...] in document order.
  2. For each duplicated (page, mcid), pick ONE keeper:
       a. the element the ParentTree page array maps that MCID to, else
       b. the claimant element with the most kids (the real container), else
       c. the first claimant in document order.
     All other claims are removed from their elements' /K.
  3. Elements left with an empty /K and no OBJR content are detached from
     their parent (junk placeholder Figures).  ParentTree page-array slots
     pointing at detached elements are nulled.

CLI usage:
    python duplicate_mcr_fixer.py <input.pdf> <output.pdf>
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from typing import Any, Optional

import pikepdf
from pikepdf import Array

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _elem_key(obj) -> Any:
    try:
        return obj.objgen if obj.is_indirect else id(obj)
    except Exception:
        return id(obj)


def _kid_claim(kid, inherited_pg) -> Optional[tuple]:
    """Return (page_objgen, mcid) if this kid is an MCID claim, else None."""
    if isinstance(kid, pikepdf.Dictionary):
        if str(kid.get("/Type", "")) == "/MCR":
            pg = kid.get("/Pg")
            pg_og = pg.objgen if (pg is not None and pg.is_indirect) else inherited_pg
            try:
                return (pg_og, int(kid.get("/MCID")))
            except Exception:
                return None
        return None
    try:
        return (inherited_pg, int(kid))
    except (TypeError, ValueError):
        return None


def fix_duplicate_mcrs(input_path: str, output_path: str) -> dict:
    print(f"[MCR] input={input_path!r}")
    print(f"[MCR] output={output_path!r}")

    result: dict[str, Any] = {
        "duplicate_mcids_found": 0,
        "claims_removed": 0,
        "empty_elems_detached": 0,
        "page_array_slots_nulled": 0,
    }

    with pikepdf.open(input_path) as pdf:
        struct_root = pdf.Root.get("/StructTreeRoot")
        if struct_root is None:
            pdf.save(output_path)
            print("[MCR] no StructTreeRoot — nothing to do")
            return result

        # ------------------------------------------------------------------
        # ParentTree page arrays: (page_objgen, mcid) -> elem objgen
        # ------------------------------------------------------------------
        page_sp = {}
        for p in pdf.pages:
            sp = p.get("/StructParents")
            if sp is not None:
                page_sp[int(sp)] = p.obj.objgen

        pt_owner: dict[tuple, Any] = {}
        page_arrays: dict[Any, pikepdf.Array] = {}

        def _scan_numtree(node):
            if "/Nums" in node:
                nums = node["/Nums"]
                for i in range(0, len(nums) - 1, 2):
                    key, val = int(nums[i]), nums[i + 1]
                    pg_og = page_sp.get(key)
                    if pg_og is None or not isinstance(val, pikepdf.Array):
                        continue
                    page_arrays[pg_og] = val
                    for mcid in range(len(val)):
                        el = val[mcid]
                        if isinstance(el, pikepdf.Dictionary) and el.is_indirect:
                            pt_owner[(pg_og, mcid)] = el.objgen
            for kid in (node.get("/Kids") or []):
                _scan_numtree(kid)

        pt = struct_root.get("/ParentTree")
        if pt is not None:
            _scan_numtree(pt)

        # ------------------------------------------------------------------
        # 1. Collect all MCID claims in the reachable tree (document order)
        # ------------------------------------------------------------------
        claims: dict[tuple, list] = defaultdict(list)  # (pg,mcid) -> [(elem, kid_idx_marker)]
        parent_of: dict[Any, pikepdf.Dictionary] = {}
        seen: set = set()

        def _walk(node, inherited_pg):
            if not isinstance(node, pikepdf.Dictionary):
                return
            key = _elem_key(node)
            if key in seen:
                return
            seen.add(key)
            pg = node.get("/Pg")
            pg_og = pg.objgen if (pg is not None and pg.is_indirect) else inherited_pg
            k = node.get("/K")
            if k is None:
                return
            kids = list(k) if isinstance(k, pikepdf.Array) else [k]
            for kid in kids:
                claim = _kid_claim(kid, pg_og)
                if claim is not None:
                    claims[claim].append((node, kid))
                elif isinstance(kid, pikepdf.Dictionary) and \
                        str(kid.get("/Type", "")) != "/OBJR":
                    parent_of[_elem_key(kid)] = node
                    _walk(kid, pg_og)

        k_root = struct_root.get("/K")
        roots = list(k_root) if isinstance(k_root, pikepdf.Array) else [k_root]
        for child in roots:
            if isinstance(child, pikepdf.Dictionary):
                parent_of[_elem_key(child)] = struct_root
                _walk(child, None)

        # ------------------------------------------------------------------
        # 2. Resolve duplicates
        # ------------------------------------------------------------------
        to_remove: dict[Any, list] = defaultdict(list)  # elem_key -> [kids to drop]
        elems_by_key: dict[Any, pikepdf.Dictionary] = {}

        for (pg_og, mcid), claimants in claims.items():
            if len(claimants) < 2:
                continue
            result["duplicate_mcids_found"] += 1

            keeper_idx = 0
            owner_og = pt_owner.get((pg_og, mcid))
            if owner_og is not None:
                for i, (el, _kid) in enumerate(claimants):
                    if el.is_indirect and el.objgen == owner_og:
                        keeper_idx = i
                        break
                else:
                    owner_og = None
            if owner_og is None:
                # prefer the claimant element with the most kids
                def _nkids(el):
                    kk = el.get("/K")
                    return len(kk) if isinstance(kk, pikepdf.Array) else (0 if kk is None else 1)
                keeper_idx = max(range(len(claimants)),
                                 key=lambda i: _nkids(claimants[i][0]))

            for i, (el, kid) in enumerate(claimants):
                if i == keeper_idx:
                    continue
                ek = _elem_key(el)
                elems_by_key[ek] = el
                to_remove[ek].append(kid)
                result["claims_removed"] += 1

            kept_el = claimants[keeper_idx][0]
            print(f"[MCR] pg={pg_og} MCID={mcid}: {len(claimants)} claims -> "
                  f"keeping elem {kept_el.objgen if kept_el.is_indirect else '?'}"
                  f" ({str(kept_el.get('/S'))})")

        # Also drop EXTRA duplicate claims kept inside the SAME element
        # (e.g. one Figure with four MCRs all to MCID 0): to_remove holds
        # kid objects; removal below deletes each listed kid instance once.

        # ------------------------------------------------------------------
        # 3. Apply removals
        # ------------------------------------------------------------------
        detached: set = set()
        for ek, drop_kids in to_remove.items():
            el = elems_by_key[ek]
            k = el.get("/K")
            kids = list(k) if isinstance(k, pikepdf.Array) else [k]
            new_kids = []
            drop_left = list(drop_kids)
            for kid in kids:
                hit = None
                for d in drop_left:
                    same = False
                    try:
                        if isinstance(kid, pikepdf.Dictionary) and \
                                isinstance(d, pikepdf.Dictionary):
                            same = (kid.is_indirect and d.is_indirect
                                    and kid.objgen == d.objgen)
                        else:
                            same = (not isinstance(kid, pikepdf.Dictionary)
                                    and not isinstance(d, pikepdf.Dictionary)
                                    and int(kid) == int(d))
                    except Exception:
                        same = False
                    if same:
                        hit = d
                        break
                if hit is not None:
                    drop_left.remove(hit)
                else:
                    new_kids.append(kid)
            if new_kids:
                el["/K"] = Array(new_kids)
            else:
                # junk placeholder (e.g. <Figure Alt="Figure 3"> with one
                # bogus MCR): detach from its parent entirely
                try:
                    del el["/K"]
                except Exception:
                    pass
                parent = parent_of.get(ek)
                if parent is not None:
                    pk = parent.get("/K")
                    pkids = list(pk) if isinstance(pk, pikepdf.Array) else [pk]
                    kept = [c for c in pkids
                            if not (isinstance(c, pikepdf.Dictionary)
                                    and _elem_key(c) == ek)]
                    parent["/K"] = Array(kept)
                    detached.add(ek)
                    result["empty_elems_detached"] += 1
                    print(f"[MCR] detached empty elem "
                          f"{el.objgen if el.is_indirect else '?'} "
                          f"({str(el.get('/S'))}, Alt={str(el.get('/Alt'))[:40]!r})")

        # ------------------------------------------------------------------
        # 4. Null ParentTree page-array slots pointing at detached elems
        # ------------------------------------------------------------------
        if detached:
            for pg_og, arr in page_arrays.items():
                for mcid in range(len(arr)):
                    el = arr[mcid]
                    if isinstance(el, pikepdf.Dictionary) and \
                            _elem_key(el) in detached:
                        arr[mcid] = None
                        result["page_array_slots_nulled"] += 1

        pdf.save(output_path)

    print(f"[MCR] done: dup_mcids={result['duplicate_mcids_found']} "
          f"claims_removed={result['claims_removed']} "
          f"elems_detached={result['empty_elems_detached']} "
          f"slots_nulled={result['page_array_slots_nulled']}")
    print(f"[MCR] saved -> {output_path}")
    return result


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: duplicate_mcr_fixer.py <input.pdf> <output.pdf>")
        sys.exit(1)
    res = fix_duplicate_mcrs(sys.argv[1], sys.argv[2])
    print(json.dumps(res, indent=2))
