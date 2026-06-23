"""
artifact_fixer.py  --  detect and fix artifact-related PDF/UA issues.

Two fixes applied:
  1. Artifact regions containing real text → re-tagged as MCID-tagged <P> content
  2. Decorative fill regions marked /Artifact /Type/Layout → /Type/Background

Public API:
    find_artifact_issues(pdf_path) -> list[dict]
    fix_artifact_issues(pdf_path)  -> dict  {text_fixed, bg_fixed, skipped}
"""
from __future__ import annotations
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

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

    * Decorative fills /Type/Layout  →  /Type/Background
    * Text artifacts: convert the BDC tag to an MCID-tagged <P> block and
      wire the new MCID into the struct tree / ParentTree.

    Returns {text_fixed, bg_fixed, skipped}.
    """
    try:
        import pikepdf
        from pikepdf import Name, Dictionary, Array, Integer
    except ImportError as e:
        logger.warning("artifact_fixer: %s", e)
        return {'text_fixed': 0, 'bg_fixed': 0, 'skipped': 0}

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

                # Read the content stream(s)
                is_array = isinstance(contents, pikepdf.Array)
                if is_array:
                    stream_bytes = b''.join(_read_stream(s) for s in contents)
                else:
                    stream_bytes = _read_stream(contents)

                stream_text = stream_bytes.decode('latin-1')
                new_text    = stream_text
                changed     = False

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

    logger.info(
        "artifact_fixer: text_fixed=%d bg_fixed=%d skipped=%d",
        text_fixed, bg_fixed, skipped,
    )
    return {'text_fixed': text_fixed, 'bg_fixed': bg_fixed, 'skipped': skipped}
