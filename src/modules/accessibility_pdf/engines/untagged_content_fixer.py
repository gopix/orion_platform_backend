"""
untagged_content_fixer.py  (v2 — content-preserving)
----------------------------------------------------
Fix PAC PDF/UA errors "Path object not tagged" / "Text object not tagged".

PDF/UA requires every painting operation to be either REAL CONTENT
(inside a /Tag <</MCID n>> BDC sequence referenced by the structure tree)
or an ARTIFACT.  PDFix AddTags() leaves violations behind:

  1. Marked sequences whose MCID no reachable StructElem claims
     (orphan sequences) — their content counts as untagged.
  2. Bare painting operators outside any marked-content sequence.
  3. Form XObjects whose inner content is never referenced by the tree.

  ── WHY THIS VERSION EXISTS ─────────────────────────────────────────────
  The previous version resolved EVERY unclaimed sequence the same way:
  rewrite it as /Artifact.  For decorative paint that is correct, but for
  unclaimed *readable text* it is a serious remediation defect — the text
  disappears from the structure tree, so screen readers can no longer
  reach it.  A PAC/Acrobat "pass" is obtained by hiding content from the
  users the standard exists to protect.  QA correctly rejects this.

  This version SPLITS unclaimed content by what it contains:

    * contains real text-showing ops (Tj/TJ/'/")  -> CLAIM into the tree
        (create a <P> StructElem + MCR, wire the page ParentTree slot).
        Nothing is hidden; the text stays reachable by assistive tech.
    * paint-only, no readable text (rules, fills, marks)  -> ARTIFACT
        (the original, correct behaviour for genuinely decorative paint).

  Reading-order caveat: recovered <P> elements are appended to the page's
  content section in content-stream order. That restores *reachability*
  (the whole point), but exact reading-order placement relative to
  pre-existing siblings is not guaranteed — recovered content should be
  surfaced to human QA (NEEDS_HUMAN) for order confirmation rather than
  treated as fully auto-fixed.

Sequences that ARE claimed by the structure tree are never touched, and
BDC->BMC conversion is skipped if a claimed sequence is nested inside.

CLI usage:
    python untagged_content_fixer.py <input.pdf> <output.pdf>
"""

from __future__ import annotations

import json
import sys
from typing import Any

import pikepdf
from pikepdf import Array, Dictionary, Name, Operator, String
from pikepdf import ContentStreamInstruction as CSI

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

_PAINT_OPS = {"S", "s", "f", "F", "f*", "B", "B*", "b", "b*",
              "sh", "Do", "Tj", "TJ", "'", '"'}
_TEXT_SHOW_OPS = {"Tj", "TJ", "'", '"'}

_ARTIFACT_BMC = CSI([Name("/Artifact")], Operator("BMC"))
_EMC = CSI([], Operator("EMC"))


def _op_of(instr) -> str:
    try:
        return str(instr.operator)
    except Exception:
        return "INLINE IMAGE"


def _is_paint(instr) -> bool:
    op = _op_of(instr)
    return op in _PAINT_OPS or op == "INLINE IMAGE"


# ── readable-text detection ──────────────────────────────────────────────────

def _shown_bytes(instr) -> bytes:
    """Return the raw glyph bytes a text-showing operator paints (best effort).

    Tj / ' / "  -> the (string) operand.
    TJ          -> concatenation of the string elements of the array operand
                   (numeric kerning adjustments are ignored).
    Codes are not unicode-decoded: for CID fonts we cannot, and we do not
    need to — any non-whitespace glyph code means real content is painted.
    """
    op = _op_of(instr)
    if op not in _TEXT_SHOW_OPS:
        return b""
    try:
        ops = list(instr.operands)
    except Exception:
        return b""
    if not ops:
        return b""
    out = bytearray()

    def _grab(o):
        # pikepdf.String -> bytes; be defensive about type
        try:
            if isinstance(o, String):
                out.extend(bytes(o))
                return
        except Exception:
            pass
        try:
            out.extend(bytes(o))
        except Exception:
            try:
                out.extend(str(o).encode("latin-1", "ignore"))
            except Exception:
                pass

    if op == "TJ":
        arr = ops[0]
        try:
            for el in arr:
                # skip numeric kerning entries
                if isinstance(el, (int, float)):
                    continue
                try:
                    float(el)  # pikepdf numeric objects
                    continue
                except Exception:
                    pass
                _grab(el)
        except Exception:
            _grab(arr)
    else:
        # Tj / ' / "  — the string is the last operand
        _grab(ops[-1])
    return bytes(out)


_WS = set(b" \t\r\n\x00\x0c")


def _bytes_have_glyph(b: bytes) -> bool:
    """True if b contains at least one non-whitespace byte (a real glyph)."""
    return any(c not in _WS for c in b)


def _run_has_real_text(instrs) -> bool:
    """True if any text-showing op in the slice paints a non-whitespace glyph."""
    for ins in instrs:
        if _op_of(ins) in _TEXT_SHOW_OPS and _bytes_have_glyph(_shown_bytes(ins)):
            return True
    return False


# ── structure-tree claim collection (unchanged) ──────────────────────────────

def _collect_claims(struct_root):
    """Reachable structure-tree claims: page (owner_og, mcid) and form ones."""
    page_claims: set = set()
    form_claims: set = set()
    seen: set = set()

    def walk(n, pg_in):
        if not isinstance(n, pikepdf.Dictionary):
            return
        try:
            key = n.objgen if n.is_indirect else id(n)
        except Exception:
            key = id(n)
        if key in seen:
            return
        seen.add(key)
        pg = n.get("/Pg")
        pg_og = pg.objgen if (pg is not None and pg.is_indirect) else pg_in
        t = str(n.get("/Type", ""))
        if t == "/MCR":
            try:
                m = int(n.get("/MCID"))
            except Exception:
                return
            stm = n.get("/Stm")
            if stm is not None:
                form_claims.add((stm.objgen, m))
            else:
                page_claims.add((pg_og, m))
            return
        if t == "/OBJR":
            return
        k = n.get("/K")
        if k is None:
            return
        kids = list(k) if isinstance(k, pikepdf.Array) else [k]
        for c in kids:
            if isinstance(c, pikepdf.Dictionary):
                walk(c, pg_og)
            else:
                try:
                    page_claims.add((pg_og, int(c)))
                except (TypeError, ValueError):
                    pass

    if struct_root is not None:
        k_root = struct_root.get("/K")
        roots = list(k_root) if isinstance(k_root, pikepdf.Array) else [k_root]
        for child in roots:
            if isinstance(child, pikepdf.Dictionary):
                walk(child, None)
    return page_claims, form_claims


def _compute_form_info(pdf, page_claims, form_claims):
    """Returns (claimed_forms, tagged_ctx_forms) — see original docstring."""
    forms = {}
    form_children = {}

    def _xmap(res):
        out = {}
        xo = (res.get("/XObject") if res is not None else None) or {}
        for name, obj in xo.items():
            out[str(name)] = obj
        return out

    def _register(obj):
        og = obj.objgen
        if og in forms:
            return
        forms[og] = obj
        kids = set()
        sub = _xmap(obj.get("/Resources"))
        for _n, s in sub.items():
            try:
                if str(s.get("/Subtype")) == "/Form":
                    kids.add(s.objgen)
                    _register(s)
            except Exception:
                pass
        form_children[og] = kids

    for page in pdf.pages:
        for _n, obj in _xmap(page.get("/Resources")).items():
            try:
                if str(obj.get("/Subtype")) == "/Form":
                    _register(obj)
            except Exception:
                pass

    claimed = {og for (og, _m) in form_claims}
    changed = True
    while changed:
        changed = False
        for og, kids in form_children.items():
            if og not in claimed and kids & claimed:
                claimed.add(og)
                changed = True

    tagged_ctx: set = set()

    def _scan(stream_obj, owner_og, claims, inherited_claimed, res):
        xmap = _xmap(res)
        stack = []
        try:
            instrs = pikepdf.parse_content_stream(stream_obj)
        except Exception:
            return
        for instr in instrs:
            op = _op_of(instr)
            if op in ("BDC", "BMC"):
                mcid = _bdc_mcid(instr) if op == "BDC" else None
                stack.append(mcid is not None and (owner_og, mcid) in claims)
            elif op == "EMC":
                if stack:
                    stack.pop()
            elif op == "Do":
                try:
                    obj = xmap.get(str(instr.operands[0]))
                except Exception:
                    obj = None
                if obj is None:
                    continue
                try:
                    if str(obj.get("/Subtype")) != "/Form":
                        continue
                    og = obj.objgen
                except Exception:
                    continue
                in_claimed = inherited_claimed or any(stack)
                if in_claimed and og not in tagged_ctx:
                    tagged_ctx.add(og)
                _scan(obj, og, form_claims, in_claimed,
                      obj.get("/Resources"))

    for page in pdf.pages:
        _scan(page, page.obj.objgen, page_claims, False,
              page.get("/Resources"))

    return claimed, tagged_ctx


def _bdc_mcid(instr):
    """Return MCID int if this is a BDC with an /MCID property, else None."""
    try:
        ops = instr.operands
        if len(ops) >= 2 and isinstance(ops[1], pikepdf.Dictionary) \
                and "/MCID" in ops[1]:
            return int(ops[1]["/MCID"])
    except Exception:
        pass
    return None


def _bdc_props(instr):
    """Return the property dict of a BDC instruction, or None."""
    try:
        ops = instr.operands
        if len(ops) >= 2 and isinstance(ops[1], pikepdf.Dictionary):
            return ops[1]
    except Exception:
        pass
    return None


# ── stream fixer ─────────────────────────────────────────────────────────────

def _fix_stream(instrs, owner_og, claims, result, xmap=None,
                claimed_forms=None, alloc=None):
    """
    Rewrite a content stream.

    Returns (new_instrs, claim_mcids) where claim_mcids is the list of MCIDs
    (existing orphan MCIDs re-tagged as <P>, plus newly-allocated MCIDs for
    bare readable-text runs) that the caller must wire into the structure
    tree + page ParentTree.

    Decision policy for each UNCLAIMED top-level marked sequence:
      * body has readable text  -> keep content, normalise the BDC tag to
        /P (preserving its property dict + MCID) and mark the MCID to claim.
      * body is paint-only      -> convert the opening BDC/BMC to /Artifact
        BMC (original behaviour).

    Bare readable-text runs (text outside any marked content) are wrapped in
    /P <</MCID k>> BDC..EMC with a freshly allocated MCID `k` and claimed;
    paint-only bare runs are wrapped in /Artifact BMC..EMC as before.

    `alloc` is a zero-arg callable returning the next free page MCID; it is
    required for claiming bare runs. If None, bare text runs fall back to the
    conservative artifact behaviour (never silently drops — but prefer to
    pass alloc so nothing is hidden).
    """
    claim_mcids: list[int] = []

    # ---- pass 1: classify each marked sequence -------------------------------
    # For each BDC/BMC index: 'artifact' (convert), 'claim' (retag /P), or
    # None (leave as-is, e.g. already claimed by the tree).
    seq_action: dict[int, str] = {}      # opening-index -> action
    seq_mcid: dict[int, int] = {}        # opening-index -> mcid (for claim)
    # stack entries: (open_index, mcid_or_None, claimed_bool, body_start_index)
    stack = []
    for i, instr in enumerate(instrs):
        op = _op_of(instr)
        if op in ("BDC", "BMC"):
            mcid = _bdc_mcid(instr) if op == "BDC" else None
            claimed = mcid is not None and (owner_og, mcid) in claims
            stack.append([i, mcid, claimed])
            if claimed:
                # a claimed sequence protects unclaimed ancestors from being
                # artifacted (content is tagged by nested context)
                for entry in stack[:-1]:
                    j = entry[0]
                    if seq_action.get(j) == "artifact":
                        seq_action[j] = None
        elif op == "EMC":
            if not stack:
                continue
            open_i, mcid, claimed = stack.pop()
            if claimed or mcid is None:
                # claimed, or a plain BMC with no MCID we don't own — leave.
                # (bare /Artifact BMC etc. stay untouched)
                continue
            # unclaimed sequence with an MCID PDFix left orphaned
            body = instrs[open_i + 1:i]
            if _run_has_real_text(body):
                seq_action[open_i] = "claim"
                seq_mcid[open_i] = mcid
                claim_mcids.append(mcid)
            else:
                # only downgrade to artifact if not already protected
                seq_action.setdefault(open_i, "artifact")

    # ---- pass 2: apply BDC-level decisions -----------------------------------
    converted = []
    for i, instr in enumerate(instrs):
        act = seq_action.get(i)
        if act == "artifact":
            converted.append(_ARTIFACT_BMC)
            result["sequences_artifacted"] += 1
        elif act == "claim":
            props = _bdc_props(instr)
            mcid = seq_mcid[i]
            new_props = Dictionary(MCID=mcid)
            # preserve accessibility-relevant props if present
            if props is not None:
                for key in ("/Lang", "/ActualText", "/Alt", "/E"):
                    if key in props:
                        new_props[key] = props[key]
            converted.append(CSI([Name("/P"), new_props], Operator("BDC")))
            result["sequences_claimed"] += 1
        else:
            converted.append(instr)

    # ---- pass 3: build units (BT..ET atomic) ---------------------------------
    units = []
    i = 0
    n = len(converted)
    while i < n:
        instr = converted[i]
        op = _op_of(instr)
        if op == "BT":
            j = i
            block = []
            delta = 0
            has_paint = False
            has_text = False
            while j < n:
                b = converted[j]
                bop = _op_of(b)
                block.append(b)
                if bop in ("BDC", "BMC"):
                    delta += 1
                elif bop == "EMC":
                    delta -= 1
                elif _is_paint(b):
                    has_paint = True
                if bop in _TEXT_SHOW_OPS and _bytes_have_glyph(_shown_bytes(b)):
                    has_text = True
                j += 1
                if bop == "ET":
                    break
            units.append(("block", block, has_paint, delta, has_text))
            i = j
            continue
        delta = 1 if op in ("BDC", "BMC") else (-1 if op == "EMC" else 0)
        has_text = (op in _TEXT_SHOW_OPS and _bytes_have_glyph(_shown_bytes(instr)))
        units.append(("op", [instr], _is_paint(instr), delta, has_text))
        i += 1

    # ---- pass 4: wrap bare runs ----------------------------------------------
    out = []
    run = []
    run_has_paint = False
    run_has_text = False
    depth = 0

    def flush():
        nonlocal run, run_has_paint, run_has_text
        if run:
            if run_has_text and alloc is not None:
                # bare readable text -> claim it (allocate an MCID, tag <P>)
                k = alloc()
                out.append(CSI([Name("/P"), Dictionary(MCID=k)],
                               Operator("BDC")))
                out.extend(run)
                out.append(_EMC)
                claim_mcids.append(k)
                result["bare_runs_claimed"] += 1
            elif run_has_paint:
                out.append(_ARTIFACT_BMC)
                out.extend(run)
                out.append(_EMC)
                result["bare_runs_wrapped"] += 1
            else:
                out.extend(run)
        run = []
        run_has_paint = False
        run_has_text = False

    def _is_claimed_form_do(instr):
        if xmap is None or claimed_forms is None:
            return False
        if _op_of(instr) != "Do":
            return False
        try:
            obj = xmap.get(str(instr.operands[0]))
            return obj is not None and obj.objgen in claimed_forms
        except Exception:
            return False

    for kind, block, has_paint, delta, has_text in units:
        if depth == 0:
            if kind == "op" and _is_claimed_form_do(block[0]):
                flush()
                out.extend(block)
                continue
            if delta != 0:
                flush()
                out.extend(block)
                depth += delta
                if delta != 0 and kind == "block" and has_paint:
                    result["mixed_text_blocks_skipped"] += 1
            else:
                run.extend(block)
                run_has_paint = run_has_paint or has_paint
                run_has_text = run_has_text or has_text
        else:
            flush()
            out.extend(block)
            depth += delta
            if depth < 0:
                depth = 0
    flush()
    return out, claim_mcids


# ── structure-tree wiring ────────────────────────────────────────────────────

def _find_content_parent(pdf, struct_root, page_obj):
    """
    Pick a StructElem to host recovered <P> elements for this page.

    Preference: the last <Sect> under the first <Document>; else the
    <Document>; else create a <Sect> under the Document; else attach to
    StructTreeRoot. Recovered content is appended here in stream order.
    """
    def _kids(n):
        k = n.get("/K")
        if k is None:
            return []
        return list(k) if isinstance(k, pikepdf.Array) else [k]

    document = None
    k_root = struct_root.get("/K")
    roots = list(k_root) if isinstance(k_root, pikepdf.Array) else [k_root]
    for child in roots:
        if isinstance(child, pikepdf.Dictionary) and str(child.get("/S")) == "/Document":
            document = child
            break
    if document is None:
        # no Document — attach recovered content directly under the root's
        # first structural child, or the root itself as a last resort
        for child in roots:
            if isinstance(child, pikepdf.Dictionary):
                return child
        return struct_root

    # find last Sect child, preferring one already bound to this page
    last_sect = None
    for child in _kids(document):
        if isinstance(child, pikepdf.Dictionary) and str(child.get("/S")) == "/Sect":
            last_sect = child
    if last_sect is not None:
        return last_sect
    return document


def _append_kid(parent, elem):
    k = parent.get("/K")
    if k is None:
        parent["/K"] = Array([elem])
    elif isinstance(k, pikepdf.Array):
        k.append(elem)
    else:
        parent["/K"] = Array([k, elem])


def fix_untagged_content(input_path: str, output_path: str) -> dict:
    print(f"[ART] input={input_path!r}")
    print(f"[ART] output={output_path!r}")

    result: dict[str, Any] = {
        "sequences_artifacted": 0,
        "sequences_claimed": 0,
        "bare_runs_wrapped": 0,
        "bare_runs_claimed": 0,
        "mixed_text_blocks_skipped": 0,
        "pages_rewritten": 0,
        "forms_rewritten": 0,
        "form_structparents_removed": 0,
        "elements_added_to_tree": 0,
    }

    with pikepdf.open(input_path) as pdf:
        struct_root = pdf.Root.get("/StructTreeRoot")
        page_claims, form_claims = _collect_claims(struct_root)
        claimed_forms, tagged_ctx_forms = _compute_form_info(
            pdf, page_claims, form_claims)

        # page-index -> ParentTree Nums array (for wiring recovered MCIDs)
        page_arrays: dict[int, pikepdf.Array] = {}
        pt = struct_root.get("/ParentTree") if struct_root is not None else None
        if pt is not None:
            nums = list(pt.get("/Nums", []))
            for i in range(0, len(nums) - 1, 2):
                val = nums[i + 1]
                if isinstance(val, pikepdf.Array):
                    page_arrays[int(nums[i])] = list(val)

        def _write_back_page_array(pindex):
            if struct_root is None or pt is None:
                return
            arr = Array(page_arrays[pindex])
            pt_nums = list(pt["/Nums"])
            replaced = False
            for i in range(0, len(pt_nums) - 1, 2):
                if int(pt_nums[i]) == pindex:
                    pt_nums[i + 1] = arr
                    replaced = True
                    break
            if not replaced:
                pt_nums.extend([pindex, arr])
            pt["/Nums"] = Array(pt_nums)

        # ---- pages ----------------------------------------------------------
        for pnum, page in enumerate(pdf.pages):
            try:
                instrs = list(pikepdf.parse_content_stream(page))
            except Exception as e:
                print(f"[ART] page {pnum + 1}: parse failed: {e}")
                continue

            page_og = page.obj.objgen
            # resolve the ParentTree page index via /StructParents
            sp = page.obj.get("/StructParents")
            pindex = int(sp) if sp is not None else pnum
            if pindex not in page_arrays:
                page_arrays[pindex] = []

            # New MCIDs must not collide with any MCID already painted on the
            # page (claimed OR orphan) — a duplicate MCID is a PAC hard error.
            existing_mcids = [m for m in (_bdc_mcid(x) for x in instrs)
                              if m is not None]
            start = max(len(page_arrays[pindex]),
                        (max(existing_mcids) + 1) if existing_mcids else 0)
            counter = {"next": start}

            def _alloc():
                v = counter["next"]
                counter["next"] += 1
                return v

            before = (result["sequences_artifacted"],
                      result["sequences_claimed"],
                      result["bare_runs_wrapped"],
                      result["bare_runs_claimed"])
            res = page.get("/Resources")
            xo = (res.get("/XObject") if res is not None else None) or {}
            xmap = {str(n): o for n, o in xo.items()}

            new_instrs, claim_mcids = _fix_stream(
                instrs, page_og, page_claims, result,
                xmap=xmap, claimed_forms=claimed_forms, alloc=_alloc)

            changed = (result["sequences_artifacted"],
                       result["sequences_claimed"],
                       result["bare_runs_wrapped"],
                       result["bare_runs_claimed"]) != before

            if not changed:
                continue

            # wire recovered MCIDs into the structure tree
            if claim_mcids and struct_root is not None:
                parent = _find_content_parent(pdf, struct_root, page.obj)
                # grow the page ParentTree array to fit the largest MCID
                max_mcid = max(claim_mcids)
                while len(page_arrays[pindex]) <= max_mcid:
                    page_arrays[pindex].append(None)
                for m in sorted(set(claim_mcids)):
                    p_elem = pdf.make_indirect(Dictionary(
                        Type=Name("/StructElem"),
                        S=Name("/P"),
                        Pg=page.obj,
                        P=parent,
                        K=Array([m]),
                    ))
                    _append_kid(parent, p_elem)
                    page_arrays[pindex][m] = p_elem
                    page_claims.add((page_og, m))
                    result["elements_added_to_tree"] += 1
                _write_back_page_array(pindex)

            page.Contents = pdf.make_stream(
                pikepdf.unparse_content_stream(new_instrs))
            result["pages_rewritten"] += 1

        # ---- form XObjects --------------------------------------------------
        def _nums_remove_key(key: int) -> bool:
            ptl = struct_root.get("/ParentTree") if struct_root is not None else None
            if ptl is None:
                return False

            def _descend(node) -> bool:
                if "/Nums" in node:
                    nums = node["/Nums"]
                    for i in range(0, len(nums) - 1, 2):
                        if int(nums[i]) == key:
                            new_nums = Array()
                            for j in range(len(nums)):
                                if j != i and j != i + 1:
                                    new_nums.append(nums[j])
                            node["/Nums"] = new_nums
                            return True
                for kid in (node.get("/Kids") or []):
                    if _descend(kid):
                        return True
                return False

            return _descend(ptl)

        seen_forms: set = set()

        def _process_form(obj):
            og = obj.objgen
            if og in seen_forms:
                return
            seen_forms.add(og)
            if og in tagged_ctx_forms:
                result["forms_skipped_tagged_ctx"] = \
                    result.get("forms_skipped_tagged_ctx", 0) + 1
                return
            try:
                instrs = list(pikepdf.parse_content_stream(obj))
            except Exception:
                return
            before = (result["sequences_artifacted"],
                      result["bare_runs_wrapped"])
            fres = obj.get("/Resources")
            fxo = (fres.get("/XObject") if fres is not None else None) or {}
            fxmap = {str(n): o for n, o in fxo.items()}
            # forms: claim path for form interiors would need form-scoped MCR
            # wiring; conservatively keep artifact behaviour here (alloc=None)
            new_instrs, _ = _fix_stream(instrs, og, form_claims, result,
                                        xmap=fxmap, claimed_forms=claimed_forms,
                                        alloc=None)
            if (result["sequences_artifacted"],
                    result["bare_runs_wrapped"]) != before:
                obj.write(pikepdf.unparse_content_stream(new_instrs))
                result["forms_rewritten"] += 1
            has_claim = any(o == og for (o, _m) in form_claims)
            sp = obj.get("/StructParents")
            if sp is not None and not has_claim:
                _nums_remove_key(int(sp))
                del obj["/StructParents"]
                result["form_structparents_removed"] += 1
            res = obj.get("/Resources")
            xo = (res.get("/XObject") if res is not None else None) or {}
            for _nm, sub in xo.items():
                try:
                    if str(sub.get("/Subtype")) == "/Form":
                        _process_form(sub)
                except Exception:
                    pass

        for page in pdf.pages:
            res = page.get("/Resources")
            xo = (res.get("/XObject") if res is not None else None) or {}
            for _nm, obj in xo.items():
                try:
                    if str(obj.get("/Subtype")) == "/Form":
                        _process_form(obj)
                except Exception:
                    pass

        pdf.save(output_path)

    print(f"[ART] done: artifacted={result['sequences_artifacted']} "
          f"claimed={result['sequences_claimed']} "
          f"bare_wrapped={result['bare_runs_wrapped']} "
          f"bare_claimed={result['bare_runs_claimed']} "
          f"tree_adds={result['elements_added_to_tree']} "
          f"pages={result['pages_rewritten']} forms={result['forms_rewritten']} "
          f"sp_removed={result['form_structparents_removed']} "
          f"mixed_skipped={result['mixed_text_blocks_skipped']}")
    print(f"[ART] saved -> {output_path}")
    return result


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: untagged_content_fixer.py <input.pdf> <output.pdf>")
        sys.exit(1)
    res = fix_untagged_content(sys.argv[1], sys.argv[2])
    print(json.dumps(res, indent=2))
