"""
link_fixer.py  --  detect and fix missing <Link> structure elements (PDF/UA).
"""

from __future__ import annotations
import logging, re
from pathlib import Path

logger = logging.getLogger(__name__)
LINK_RE = re.compile(r'https?://[^\s|,;]+|www\.[^\s|,;]+|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')

def _to_pdf_coords(x0, top, x1, bottom, page_height):
    return [x0, page_height - bottom, x1, page_height - top]

def _rects_overlap(r1, r2, tol=2.0):
    return not (r1[2]+tol < r2[0] or r2[2]+tol < r1[0] or r1[3]+tol < r2[1] or r2[3]+tol < r1[1])

def _normalise_uri(raw):
    if raw.startswith('www.'): return 'https://' + raw
    if '@' in raw and not raw.startswith('mailto:'): return 'mailto:' + raw
    return raw

def _group_chars_into_lines(chars, y_tolerance=3.0):
    if not chars: return []
    sorted_chars = sorted(chars, key=lambda c: (round(c['top']/y_tolerance), c['x0']))
    lines, cur, cur_top = [], [sorted_chars[0]], sorted_chars[0]['top']
    for ch in sorted_chars[1:]:
        if abs(ch['top'] - cur_top) <= y_tolerance: cur.append(ch)
        else: lines.append(cur); cur = [ch]; cur_top = ch['top']
    if cur: lines.append(cur)
    return lines

def _scan_page_for_links(plumber_page, page_height):
    chars = plumber_page.chars
    if not chars: return []
    results = []
    for line_chars in _group_chars_into_lines(chars):
        line_text = ''.join(c['text'] for c in line_chars)
        for match in LINK_RE.finditer(line_text):
            raw = match.group(0).rstrip('.,;)')
            s, e = match.start(), match.start() + len(raw)
            span = line_chars[s:e]
            if not span: continue
            x0 = min(c['x0'] for c in span); top = min(c['top'] for c in span)
            x1 = max(c['x1'] for c in span); bot = max(c['bottom'] for c in span)
            mcids = {c.get('mcid') for c in span if c.get('mcid') is not None}
            results.append({'uri': _normalise_uri(raw),
                            'rect': _to_pdf_coords(x0, top, x1, bot, page_height),
                            'mcids': mcids})
    return results

def _is_link_missing(pp, uri, rect):
    try:
        import pikepdf; from pikepdf import Name
    except ImportError: return True
    normalised = uri.lower()
    for annot in pp.get('/Annots', []):
        try:
            if annot.get('/Subtype') != Name('/Link'): continue
            a = annot.get('/A')
            if a and a.get('/S') == Name('/URI') and str(a['/URI']).lower() == normalised: return False
            er = list(annot.get('/Rect', []))
            if er and _rects_overlap(er, rect): return False
        except Exception: continue
    return True

def _find_document_element(sr):
    import pikepdf; from pikepdf import Name
    GROUPING = {Name('/Document'), Name('/Part'), Name('/Art'), Name('/Sect'), Name('/Div'), Name('/NonStruct')}
    k = sr.get('/K')
    if k is None: return sr
    candidates = list(k) if isinstance(k, pikepdf.Array) else [k]
    for item in candidates:
        try:
            if item.get('/S') in GROUPING: return item
        except Exception: continue
    return sr

def _get_next_struct_parent_key(sr):
    if '/ParentTreeNextKey' in sr: return int(sr['/ParentTreeNextKey'])
    pt = sr.get('/ParentTree')
    if pt:
        nums = pt.get('/Nums')
        if nums and len(nums) >= 2: return max(int(nums[i]) for i in range(0, len(nums), 2)) + 1
    return 0

def _build_page_arrays(sr):
    import pikepdf
    result = {}
    pt = sr.get('/ParentTree')
    if pt is None: return result
    nums = list(pt.get('/Nums', []))
    for i in range(0, len(nums), 2):
        val = nums[i+1]
        if isinstance(val, pikepdf.Array): result[int(nums[i])] = val
    return result

def _add_link_annotation(pdf, pdf_page, rect, uri, sp_key):
    import pikepdf; from pikepdf import Dictionary, Array, Name, String
    if uri.startswith('mailto:'):
        contents_label = f"Send email to {uri[7:]}"
    else:
        contents_label = f"Open link: {uri}"
    annot = pdf.make_indirect(Dictionary(
        Type=Name('/Annot'), Subtype=Name('/Link'), Rect=Array(rect),
        A=Dictionary(S=Name('/URI'), URI=String(uri)),
        Contents=String(contents_label),
        Border=Array([0, 0, 0]), F=pikepdf.Integer(4),
        StructParent=pikepdf.Integer(sp_key)))
    if '/Annots' not in pdf_page: pdf_page['/Annots'] = pikepdf.Array()
    pdf_page['/Annots'].append(annot)
    return annot

def _add_link_struct_with_mcid(pdf, sr, page_arrays, pdf_page, page_idx, mcid, annot_pairs):
    import pikepdf; from pikepdf import Dictionary, Array, Name
    page_array = page_arrays.get(page_idx)
    mcid_owner = None
    if page_array is not None:
        arr = list(page_array)
        if 0 <= mcid < len(arr):
            try: mcid_owner = arr[mcid]
            except Exception: pass
    k_items = [pikepdf.Integer(mcid)]
    for annot, _ in annot_pairs:
        objr = pdf.make_indirect(Dictionary(Type=Name('/OBJR'), Obj=annot, Pg=pdf_page.obj))
        k_items.append(objr)
    parent = mcid_owner if mcid_owner is not None else _find_document_element(sr)
    link_elem = pdf.make_indirect(Dictionary(
        Type=Name('/StructElem'), S=Name('/Link'),
        Pg=pdf_page.obj, K=Array(k_items), P=parent))
    if mcid_owner is not None:
        old_k = mcid_owner.get('/K')
        if isinstance(old_k, pikepdf.Array):
            new_k = Array([]); replaced = False
            for item in list(old_k):
                try:
                    if not replaced and int(item) == mcid: new_k.append(link_elem); replaced = True
                    else: new_k.append(item)
                except Exception: new_k.append(item)
            mcid_owner['/K'] = new_k
        else:
            mcid_owner['/K'] = Array([link_elem])
    else:
        k = parent.get('/K')
        if k is None: parent['/K'] = Array([link_elem])
        elif isinstance(k, pikepdf.Array): k.append(link_elem)
        else: parent['/K'] = Array([k, link_elem])
    if page_array is not None: page_array[mcid] = link_elem
    pt = sr.get('/ParentTree')
    if pt is None:
        pt = pdf.make_indirect(Dictionary(Nums=Array([]))); sr['/ParentTree'] = pt
    nums = pt.get('/Nums')
    if nums is None: nums = Array([]); pt['/Nums'] = nums
    max_sp = -1
    for _, sp_key in annot_pairs:
        nums.append(pikepdf.Integer(sp_key)); nums.append(link_elem); max_sp = max(max_sp, sp_key)
    sr['/ParentTreeNextKey'] = pikepdf.Integer(max_sp + 1)

def _add_link_struct_objr_only(pdf, sr, pdf_page, annot, sp_key):
    import pikepdf; from pikepdf import Dictionary, Array, Name
    parent = _find_document_element(sr)
    objr = pdf.make_indirect(Dictionary(Type=Name('/OBJR'), Obj=annot, Pg=pdf_page.obj))
    le = pdf.make_indirect(Dictionary(Type=Name('/StructElem'), S=Name('/Link'),
        Pg=pdf_page.obj, K=Array([objr]), P=parent))
    k = parent.get('/K')
    if k is None: parent['/K'] = Array([le])
    elif isinstance(k, pikepdf.Array): k.append(le)
    else: parent['/K'] = Array([k, le])
    pt = sr.get('/ParentTree')
    if pt is None:
        pt = pdf.make_indirect(Dictionary(Nums=Array([]))); sr['/ParentTree'] = pt
    nums = pt.get('/Nums')
    if nums is None: nums = Array([]); pt['/Nums'] = nums
    nums.append(pikepdf.Integer(sp_key)); nums.append(le)
    sr['/ParentTreeNextKey'] = pikepdf.Integer(sp_key + 1)

def find_missing_links(pdf_path):
    try: import pdfplumber, pikepdf
    except ImportError as e: logger.warning('link_fixer: %s', e); return []
    missing = []
    try:
        with pdfplumber.open(pdf_path) as plumb, pikepdf.open(pdf_path) as kpdf:
            for idx, (pp, kp) in enumerate(zip(plumb.pages, kpdf.pages)):
                for lnk in _scan_page_for_links(pp, pp.height):
                    if _is_link_missing(kp, lnk['uri'], lnk['rect']):
                        missing.append({'page': idx+1, 'uri': lnk['uri'], 'rect': lnk['rect']})
    except Exception as exc: logger.error('find_missing_links: %s', exc)
    return missing

def fix_missing_link_tags(pdf_path):
    try: import pdfplumber, pikepdf
    except ImportError as e: logger.warning('link_fixer: %s', e); return {'added': 0, 'skipped': 0}
    added = skipped = 0
    try:
        page_links = {}
        with pdfplumber.open(pdf_path) as plumb:
            for idx, page in enumerate(plumb.pages):
                links = _scan_page_for_links(page, page.height)
                if links: page_links[idx] = links
        if not page_links:
            return {'added': 0, 'skipped': 0}
        with pikepdf.open(pdf_path, allow_overwriting_input=True) as pdf:
            sr = pdf.Root.get('/StructTreeRoot')
            page_arrays = _build_page_arrays(sr) if sr else {}
            next_key = _get_next_struct_parent_key(sr) if sr else 0
            for page_idx, links in page_links.items():
                pdf_page = pdf.pages[page_idx]
                missing_links = [l for l in links if _is_link_missing(pdf_page, l['uri'], l['rect'])]
                skipped += len(links) - len(missing_links)
                if not missing_links: continue
                mcid_groups = {}; no_mcid = []
                for lnk in missing_links:
                    if lnk['mcids']: mcid_groups.setdefault(frozenset(lnk['mcids']), []).append(lnk)
                    else: no_mcid.append(lnk)
                for mcid_set, group_links in mcid_groups.items():
                    mcid = sorted(mcid_set)[0]; annot_pairs = []
                    for lnk in group_links:
                        a = _add_link_annotation(pdf, pdf_page, lnk['rect'], lnk['uri'], next_key)
                        annot_pairs.append((a, next_key)); next_key += 1; added += 1
                    if sr:
                        _add_link_struct_with_mcid(pdf, sr, page_arrays, pdf_page, page_idx, mcid, annot_pairs)
                for lnk in no_mcid:
                    a = _add_link_annotation(pdf, pdf_page, lnk['rect'], lnk['uri'], next_key)
                    if sr: _add_link_struct_objr_only(pdf, sr, pdf_page, a, next_key)
                    next_key += 1; added += 1
            pdf.save(pdf_path)
        logger.info('link_fixer: done added=%d skipped=%d', added, skipped)
    except Exception as exc:
        logger.error('fix_missing_link_tags: %s', exc, exc_info=True)
    return {'added': added, 'skipped': skipped}
