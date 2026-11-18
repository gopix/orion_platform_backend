"""
artifact_fixer.py  --  detect and fix artifact-related PDF/UA issues.

Three fixes applied:
  1. Artifact regions containing real text → re-tagged as MCID-tagged <P> content
  2. Decorative fill regions marked /Artifact /Type/Layout → /Type/Background
  3. MCID-tagged BDC…EMC blocks nested *inside* /Artifact BDC…EMC blocks →
     strip the inner BDC/EMC markers (PAC error "Tagged content inside artifact")

Public API:
    find_artifact_issues(pdf_path) -> list[dict]
    fix_artifact_issues(pdf_path)  -> dict  {text_fixed, bg_fixed, artifact_fixed, skipped}
"""
from __future__ import annotations
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# Footer/header band fraction reserved for running_artifact_fixer. Fix 2 will
# not convert text inside this top/bottom band into <P>. Keep in sync with
# running_artifact_fixer's ORION_FOOTER_BAND_FRAC (default 0.08); use a slightly
# larger default here so Fix 2 yields the boundary rather than fighting for it.
import os as _os
_FOOTER_BAND_FRAC = float(_os.environ.get("ORION_FOOTER_BAND_FRAC", "0.10"))

# ── content stream helpers ───────────────────────────────────────────────────

# Matches an Artifact BDC tag and its dict, e.g.
#   /Artifact <</BBox[...]/Type/Layout>>BDC
_ARTIFACT_BDC_RE = re.compile(
    rb'/Artifact\s*(<<(?:[^<>]|<[^<>]*>)*>>)\s*BDC'
)
_TYPE_LAYOUT_RE  = re.compile(rb'/Type\s*/Layout')
_TYPE_BG_RE      = re.compile(rb'/Type\s*/Background')
# Text operators that indicate actual readable content
_TEXT_OP_RE      = re.compile(rb'\bBT\b.*?\bET\b', re.DOTALL)



def _read_stream(obj) -> bytes:
    """Decode a pikepdf stream object."""
    try:
        return obj.read_bytes()
    except Exception:
        return bytes(obj.read_raw_bytes())


def _extract_bdc_emc_blocks(stream: bytes) -> list[dict]:
    """
    Return list of {start, end, header_bytes, body_bytes, tag_type} for each
    /Artifact BDC...EMC block (non-nested, outer level only).
    """
    blocks = []
    depth = 0
    i = 0
    current: dict | None = None

    while i < len(stream):
        # Look for BDC keyword
        if stream[i:i+3] == b'BDC':
            if depth == 0 and current is None:
                # Find the /Artifact tag before this BDC
                preceding = stream[max(0, i-200):i]
                m = _ARTIFACT_BDC_RE.search(preceding + b'BDC')
                if m:
                    tag_bytes = m.group(1)
                    current = {
                        'start': i + 3,
                        'header_bytes': tag_bytes,
                        'is_layout': bool(_TYPE_LAYOUT_RE.search(tag_bytes)),
                        'is_bg':     bool(_TYPE_BG_RE.search(tag_bytes)),
                    }
            depth += 1
            i += 3
        elif stream[i:i+3] == b'EMC':
            depth -= 1
            if depth == 0 and current is not None:
                current['end'] = i
                current['body_bytes'] = stream[current['start']:i]
                blocks.append(current)
                current = None
            i += 3
        else:
            i += 1

    return blocks


def _block_has_text(body: bytes) -> bool:
    """Return True if the BDC body contains text-drawing operators."""
    return bool(_TEXT_OP_RE.search(body))


def _block_is_fill_only(body: bytes) -> bool:
    """Return True if the block only draws filled paths (no text, no images)."""
    has_text = _TEXT_OP_RE.search(body)
    has_image = b' Do' in body or b'\nDo' in body
    has_fill  = re.search(rb'\b(f\*?|F|B|b)\s*\n', body)
    return bool(has_fill and not has_text and not has_image)


# Text-positioning operators, used to locate a block vertically so Fix 2 can
# leave the running header/footer band to running_artifact_fixer.
_TM_RE = re.compile(
    rb'([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+Tm'
)
_TD_RE = re.compile(rb'([-\d.]+)\s+([-\d.]+)\s+T[dD]')


def _block_min_text_y(body: bytes):
    """
    Best-effort lowest text baseline y (PDF space, origin bottom-left) in a
    content-stream fragment. Returns None if no positioning operator is found.
    Used only to decide whether a block sits in the footer band.
    """
    ys = []
    for m in _TM_RE.finditer(body):
        try:
            ys.append(float(m.group(6)))
        except Exception:
            pass
    for m in _TD_RE.finditer(body):
        try:
            ys.append(float(m.group(2)))
        except Exception:
            pass
    return min(ys) if ys else None


# ── Fix 3: pikepdf tokeniser-based "tagged content inside artifact" fix ───────

def fix_tagged_in_artifacts(pdf_path: str) -> dict:
    """
    Fix PAC Matterhorn 14-005: "Tagged content present inside an artifact".

    Uses pikepdf.parse_content_stream() — the proper PDF tokeniser — to locate
    /tag <</MCID N>> BDC…EMC blocks nested inside /Artifact BDC…EMC blocks.
    For each such inner block the BDC and its matching EMC are omitted from the
    rebuilt stream (drawing operators inside the block are preserved), and the
    MCID is removed from its owning structure element's /K list.

    Must be called AFTER fix_artifact_issues() has already saved the file.

    Returns {'pages_fixed': int, 'mcids_removed': int}.
    """
    try:
        import pikepdf
    except ImportError as e:
        logger.warning("fix_tagged_in_artifacts: %s", e)
        return {'pages_fixed': 0, 'mcids_removed': 0}

    pages_fixed   = 0
    mcids_removed = 0

    try:
        with pikepdf.open(pdf_path, allow_overwriting_input=True) as pdf:
            struct_root = pdf.Root.get('/StructTreeRoot')

            # Build ParentTree: page_idx → list of struct elements indexed by MCID
            page_arrays: dict[int, list] = {}
            if struct_root:
                pt = struct_root.get('/ParentTree')
                if pt:
                    nums = list(pt.get('/Nums', []))
                    for i in range(0, len(nums) - 1, 2):
                        val = nums[i + 1]
                        if isinstance(val, pikepdf.Array):
                            page_arrays[int(nums[i])] = list(val)

            for pi, page in enumerate(pdf.pages):
                new_tokens: list         = []
                total_depth              = 0   # depth across ALL BDC/BMC blocks
                artifact_depth           = 0   # depth counting only /Artifact blocks
                # total_depth value recorded just BEFORE each /Artifact BDC incremented it
                artifact_entry_depths: list[int] = []
                # Same for MCID BDC tokens we are eliding (so their EMC can be dropped)
                skip_entry_depths: list[int]     = []
                stripped_mcids: list[int]        = []

                try:
                    for operands, operator in pikepdf.parse_content_stream(page):
                        op = str(operator)

                        if op in ('BDC', 'BMC'):
                            is_artifact = (
                                len(operands) >= 1
                                and str(operands[0]) == '/Artifact'
                            )
                            depth_at_entry = total_depth
                            total_depth   += 1

                            if is_artifact:
                                artifact_depth += 1
                                artifact_entry_depths.append(depth_at_entry)
                                new_tokens.append((operands, operator))

                            elif artifact_depth > 0 and op == 'BDC':
                                # Inside /Artifact region — check for MCID
                                mcid: int | None = None
                                if len(operands) >= 2:
                                    props = operands[1]
                                    if isinstance(props, pikepdf.Dictionary):
                                        mv = props.get('/MCID')
                                        if mv is not None:
                                            try:
                                                mcid = int(mv)
                                            except Exception:
                                                pass

                                if mcid is not None:
                                    # Elide this BDC; remember depth to drop its EMC
                                    skip_entry_depths.append(depth_at_entry)
                                    stripped_mcids.append(mcid)
                                    # intentionally NOT added to new_tokens
                                else:
                                    new_tokens.append((operands, operator))

                            else:
                                new_tokens.append((operands, operator))

                        elif op == 'EMC':
                            total_depth -= 1
                            depth_after  = total_depth

                            if (artifact_entry_depths
                                    and depth_after == artifact_entry_depths[-1]):
                                # Closing an /Artifact block — keep its EMC
                                artifact_depth -= 1
                                artifact_entry_depths.pop()
                                new_tokens.append((operands, operator))

                            elif (skip_entry_depths
                                  and depth_after == skip_entry_depths[-1]):
                                # Closing a skipped MCID BDC block — drop this EMC too
                                skip_entry_depths.pop()
                                # intentionally NOT added to new_tokens

                            else:
                                new_tokens.append((operands, operator))

                        else:
                            new_tokens.append((operands, operator))

                except Exception as parse_err:
                    logger.warning(
                        "fix_tagged_in_artifacts page %d parse: %s", pi + 1, parse_err
                    )
                    continue

                if not stripped_mcids:
                    continue

                logger.debug(
                    "fix_tagged_in_artifacts: page=%d stripped=%s",
                    pi + 1, stripped_mcids,
                )

                # Rebuild content stream from filtered token list
                try:
                    new_stream = pikepdf.unparse_content_stream(new_tokens)
                except Exception as unparse_err:
                    logger.warning(
                        "fix_tagged_in_artifacts page %d unparse: %s",
                        pi + 1, unparse_err,
                    )
                    continue

                contents = page.get('/Contents')
                if contents is None:
                    continue
                try:
                    if isinstance(contents, pikepdf.Array):
                        contents[0].write(new_stream)
                        while len(contents) > 1:
                            del contents[-1]
                    else:
                        contents.write(new_stream)
                except Exception as write_err:
                    logger.warning(
                        "fix_tagged_in_artifacts page %d write: %s",
                        pi + 1, write_err,
                    )
                    continue

                # Remove stripped MCIDs from struct tree K lists
                pa = page_arrays.get(pi)
                if pa is not None:
                    for mcid in stripped_mcids:
                        if mcid >= len(pa):
                            continue
                        try:
                            elem = pa[mcid]
                            if not isinstance(elem, pikepdf.Dictionary):
                                continue
                            k = elem.get('/K')
                            if isinstance(k, pikepdf.Array):
                                elem['/K'] = pikepdf.Array(
                                    [x for x in k
                                     if not (isinstance(x, pikepdf.objects.Integer)
                                             and int(x) == mcid)]
                                )
                            elif (isinstance(k, pikepdf.objects.Integer)
                                  and int(k) == mcid):
                                elem['/K'] = pikepdf.Array([])
                        except Exception as ke:
                            logger.debug(
                                "fix_tagged_in_artifacts K-cleanup mcid=%d: %s",
                                mcid, ke,
                            )

                mcids_removed += len(stripped_mcids)
                pages_fixed   += 1

            pdf.save(pdf_path)

    except Exception as exc:
        logger.error("fix_tagged_in_artifacts: %s", exc, exc_info=True)

    logger.info(
        "fix_tagged_in_artifacts: pages_fixed=%d mcids_removed=%d",
        pages_fixed, mcids_removed,
    )
    return {'pages_fixed': pages_fixed, 'mcids_removed': mcids_removed}


# ── public API ───────────────────────────────────────────────────────────────

def find_artifact_issues(pdf_path: str) -> list[dict]:
    """
    Scan PDF for artifact-related issues.

    Returns list of dicts:
        {type: 'wrong_artifact_text'|'wrong_artifact_type',
         page: int (1-based), description: str}
    """
    try:
        import pikepdf
    except ImportError as e:
        logger.warning("artifact_fixer: %s", e)
        return []

    issues = []
    try:
        with pikepdf.open(pdf_path) as pdf:
            for pi, page in enumerate(pdf.pages):
                contents = page.get('/Contents')
                if contents is None:
                    continue
                if isinstance(contents, pikepdf.Array):
                    stream = b''.join(_read_stream(s) for s in contents)
                else:
                    stream = _read_stream(contents)

                for blk in _extract_bdc_emc_blocks(stream):
                    if not blk['is_layout']:
                        continue
                    if _block_has_text(blk['body_bytes']):
                        issues.append({
                            'type': 'wrong_artifact_text',
                            'page': pi + 1,
                            'description': (
                                f"Page {pi+1}: Artifact /Type/Layout block contains text — "
                                "real content is hidden from screen readers"
                            ),
                        })
                    elif _block_is_fill_only(blk['body_bytes']):
                        issues.append({
                            'type': 'wrong_artifact_type',
                            'page': pi + 1,
                            'description': (
                                f"Page {pi+1}: Decorative fill marked /Type/Layout "
                                "— should be /Type/Background"
                            ),
                        })
    except Exception as exc:
        logger.error("find_artifact_issues: %s", exc)

    return issues


def fix_artifact_issues(pdf_path: str) -> dict:
    """
    Fix artifact issues in-place:

    Fix 1 — Decorative fills /Type/Layout  →  /Type/Background
    Fix 2 — Text artifacts: convert the BDC tag to an MCID-tagged <P> block
             and wire the new MCID into the struct tree / ParentTree.
    Fix 3 — Nested MCID BDC…EMC wrappers inside /Artifact blocks → strip the
             inner BDC/EMC markers (PAC "Tagged content present inside an
             artifact").  Delegated to fix_tagged_in_artifacts() which runs as
             a second pass after Fixes 1+2 are saved.

    Returns {text_fixed, bg_fixed, artifact_fixed, skipped}.
    """
    try:
        import pikepdf
        from pikepdf import Name, Dictionary, Array, Integer
    except ImportError as e:
        logger.warning("artifact_fixer: %s", e)
        return {'text_fixed': 0, 'bg_fixed': 0, 'artifact_fixed': 0, 'skipped': 0}

    text_fixed = bg_fixed = skipped = 0

    try:
        with pikepdf.open(pdf_path, allow_overwriting_input=True) as pdf:
            struct_root = pdf.Root.get('/StructTreeRoot')

            # Build page-index → parent-tree array mapping
            page_arrays: dict[int, pikepdf.Array] = {}
            if struct_root:
                pt = struct_root.get('/ParentTree')
                if pt:
                    nums = list(pt.get('/Nums', []))
                    for i in range(0, len(nums) - 1, 2):
                        val = nums[i + 1]
                        if isinstance(val, pikepdf.Array):
                            page_arrays[int(nums[i])] = val

            for pi, page in enumerate(pdf.pages):
                contents = page.get('/Contents')
                if contents is None:
                    continue

                # Page height + footer cutoff (PDF space, origin bottom-left).
                # Fix 2 must NOT convert running header/footer text — that band
                # is owned by running_artifact_fixer, which artifacts it. Guard
                # is explicit so the boundary holds on any file, not by luck.
                try:
                    mb = page.mediabox
                    _page_h = float(mb[3]) - float(mb[1])
                except Exception:
                    _page_h = 792.0
                _footer_cutoff_y = _page_h * float(_FOOTER_BAND_FRAC)

                # Read the content stream(s)
                is_array = isinstance(contents, pikepdf.Array)
                if is_array:
                    stream_bytes = b''.join(_read_stream(s) for s in contents)
                else:
                    stream_bytes = _read_stream(contents)

                changed = False

                # ── Fix 1: /Type/Layout → /Type/Background for fills ────────
                def _fix_bg(m: re.Match) -> bytes:
                    nonlocal bg_fixed, changed
                    tag = m.group(1)
                    if _TYPE_LAYOUT_RE.search(tag):
                        body = stream_bytes[m.end():stream_bytes.find(b'EMC', m.end())]
                        if _block_is_fill_only(body):
                            bg_fixed += 1
                            changed = True
                            new_tag = _TYPE_LAYOUT_RE.sub(b'/Type/Background', tag)
                            return b'/Artifact ' + new_tag + b'BDC'
                    return m.group(0)

                new_bytes = _ARTIFACT_BDC_RE.sub(_fix_bg, stream_bytes)

                # ── Fix 2: Text artifacts → MCID-tagged <P> ─────────────────
                # Strategy: replace /Artifact<<.../Type/Layout...>>BDC with
                # /P <</MCID N>>BDC, allocating a new MCID and wiring into
                # the struct tree.
                if struct_root and page_arrays.get(pi) is not None:
                    page_array = list(page_arrays[pi])
                    next_mcid  = len(page_array)

                    def _fix_text_artifact(m: re.Match) -> bytes:
                        nonlocal text_fixed, changed, next_mcid, page_array
                        tag = m.group(1)
                        if not _TYPE_LAYOUT_RE.search(tag):
                            return m.group(0)
                        # Find the body
                        start_body = m.end()
                        end_body   = new_bytes.find(b'EMC', start_body)
                        if end_body < 0:
                            return m.group(0)
                        body = new_bytes[start_body:end_body]
                        if not _block_has_text(body):
                            return m.group(0)

                        # Footer/header guard: leave the running furniture band
                        # to running_artifact_fixer. If this text sits in the
                        # bottom (or top) band, do not convert it to <P>.
                        _by = _block_min_text_y(body)
                        if _by is not None and (
                            _by <= _footer_cutoff_y
                            or _by >= (_page_h - _footer_cutoff_y)
                        ):
                            return m.group(0)

                        # Allocate MCID
                        mcid = next_mcid
                        next_mcid += 1

                        # Find a <P> element to reuse as parent
                        # (use the last real <P> in the page array)
                        owner_p = None
                        for elem in reversed(page_array):
                            try:
                                if elem.get('/S') == Name('/P'):
                                    owner_p = elem
                                    break
                            except Exception:
                                pass

                        if owner_p is None:
                            # Fall back: create a new bare <P>
                            owner_p = pdf.make_indirect(Dictionary(
                                Type=Name('/StructElem'),
                                S=Name('/P'),
                                Pg=page.obj,
                                K=Array([]),
                                P=struct_root,
                            ))

                        # Extend the <P>'s K list
                        k = owner_p.get('/K')
                        if k is None:
                            owner_p['/K'] = Array([Integer(mcid)])
                        elif isinstance(k, pikepdf.Array):
                            k.append(Integer(mcid))
                        else:
                            owner_p['/K'] = Array([k, Integer(mcid)])

                        page_array.append(owner_p)
                        text_fixed += 1
                        changed = True

                        return (
                            b'/P <</MCID ' + str(mcid).encode() + b'>>BDC'
                        )

                    new_bytes = _ARTIFACT_BDC_RE.sub(_fix_text_artifact, new_bytes)

                    # Write back extended page array
                    if len(page_array) > len(list(page_arrays[pi])):
                        import pikepdf
                        page_arrays[pi] = Array(page_array)
                        pt_nums = list(struct_root['/ParentTree']['/Nums'])
                        for i in range(0, len(pt_nums) - 1, 2):
                            if int(pt_nums[i]) == pi:
                                pt_nums[i + 1] = page_arrays[pi]
                                break
                        struct_root['/ParentTree']['/Nums'] = Array(pt_nums)

                if not changed:
                    skipped += 1
                    continue

                # Write back the content stream
                if is_array:
                    # Write to first stream, clear the rest
                    first = contents[0]
                    first.write(new_bytes)
                    while len(contents) > 1:
                        contents.pop()
                else:
                    contents.write(new_bytes)

            pdf.save(pdf_path)

    except Exception as exc:
        logger.error("fix_artifact_issues: %s", exc, exc_info=True)
        return {
            'text_fixed': text_fixed,
            'bg_fixed': bg_fixed,
            'artifact_fixed': 0,
            'skipped': skipped,
        }

    logger.info(
        "artifact_fixer fixes 1+2: text_fixed=%d bg_fixed=%d skipped=%d",
        text_fixed, bg_fixed, skipped,
    )

    # ── Fix 3: second pass using the pikepdf tokeniser ───────────────────────
    r3 = fix_tagged_in_artifacts(pdf_path)
    artifact_fixed = r3.get('mcids_removed', 0)

    return {
        'text_fixed': text_fixed,
        'bg_fixed': bg_fixed,
        'artifact_fixed': artifact_fixed,
        'skipped': skipped,
    }
