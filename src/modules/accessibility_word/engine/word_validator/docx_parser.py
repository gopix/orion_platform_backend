"""Step 1: parse a DOCX once into a DocumentContext.

Reads the OOXML directly with zipfile and lxml. python-docx is deliberately avoided:
it invents default core properties when core.xml is absent (title "Word Document"),
which would hide a genuinely missing title.
"""
from __future__ import annotations

import hashlib
import logging
import posixpath
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from src.modules.accessibility_word.models.document_context import (
    DocumentContext,
    HyperlinkInfo,
    ImageInfo,
    ParagraphInfo,
    RunInfo,
    SectionInfo,
    TableInfo,
    TextBoxInfo,
)

logger = logging.getLogger(__name__)

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "v": "urn:schemas-microsoft-com:vml",
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "dc": "http://purl.org/dc/elements/1.1/",
    "ep": "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}
W = "{%s}" % NS["w"]
R = "{%s}" % NS["r"]
MC = "{%s}" % NS["mc"]
WP = "{%s}" % NS["wp"]
A = "{%s}" % NS["a"]
V = "{%s}" % NS["v"]

STRICT_W_NS = "http://purl.oclc.org/ooxml/wordprocessingml/main"
REL_OFFICE_DOC = "/officeDocument"
MAX_XML_PART_BYTES = 256 * 1024 * 1024
DEFAULT_FONT_SIZE_PT = 10.0

HIGHLIGHT_HEX = {
    "yellow": "FFFF00", "green": "00FF00", "cyan": "00FFFF", "magenta": "FF00FF",
    "blue": "0000FF", "red": "FF0000", "darkBlue": "000080", "darkCyan": "008080",
    "darkGreen": "008000", "darkMagenta": "800080", "darkRed": "800000",
    "darkYellow": "808000", "darkGray": "808080", "lightGray": "C0C0C0",
    "black": "000000", "white": "FFFFFF",
}
THEME_ALIASES = {"text1": "dk1", "text2": "dk2", "background1": "lt1", "background2": "lt2",
                 "dark1": "dk1", "dark2": "dk2", "light1": "lt1", "light2": "lt2"}
_HEADING_NAME = re.compile(r"^heading\s+([1-9])$", re.IGNORECASE)
_HEX = re.compile(r"^[0-9A-Fa-f]{6}$")
_TOC_FIELD = re.compile(r"(^|\s)TOC(\s|$)")


class DocxParseError(ValueError):
    """The upload is not a usable DOCX. The router turns ValueError into HTTP 400."""


def _on(el) -> bool:
    if el is None:
        return False
    return el.get(W + "val") not in ("0", "false", "off")


@dataclass
class _Style:
    style_id: str
    name: str
    type: str
    based_on: str | None
    rpr: dict
    ppr: dict
    has_shading: bool = False


@dataclass
class _WalkState:
    part: str
    container: str
    rels: dict[str, str] = field(default_factory=dict)
    table_index: int | None = None
    table_depth: int = 0
    cell_fill: str | None = None
    table_style_shaded: bool = False


class DocxParser:
    def parse(self, file_path: str) -> DocumentContext:
        path = Path(file_path)
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise DocxParseError(f"Cannot read file: {exc}") from exc
        if not zipfile.is_zipfile(path):
            raise DocxParseError("Not a valid DOCX file. It may be corrupt or password protected.")
        try:
            with zipfile.ZipFile(path) as package:
                return _Build(package, path.name, data).run()
        except zipfile.BadZipFile as exc:
            raise DocxParseError(f"Not a valid DOCX file: {exc}") from exc


class _Build:
    def __init__(self, package: zipfile.ZipFile, name: str, data: bytes):
        self.package = package
        self.names = set(package.namelist())
        self.context = DocumentContext(
            file_name=name, file_size=len(data), sha256=hashlib.sha256(data).hexdigest())
        self.theme: dict[str, str] = {}
        self.styles: dict[str, _Style] = {}
        self.default_rpr: dict = {}
        self.default_ppr: dict = {}
        self.default_paragraph_style: str | None = None
        self.page_background = "FFFFFF"
        self.current_section: str | None = None

    # ---- package helpers ------------------------------------------------
    def _xml(self, part: str):
        info = self.package.getinfo(part)
        if info.file_size > MAX_XML_PART_BYTES:
            raise DocxParseError(f"{part} is too large to process")
        # Hardened against XXE and network access.
        parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False,
                                 dtd_validation=False, huge_tree=False)
        return etree.fromstring(self.package.read(part), parser=parser)

    def _optional_xml(self, part: str, key: str | None = None):
        """Absent returns None. Malformed is recorded so dependent analyzers can fail honestly."""
        if part not in self.names:
            return None
        try:
            return self._xml(part)
        except etree.XMLSyntaxError as exc:
            self.context.failed_parts[key or part] = str(exc)
            logger.warning("Could not parse %s: %s", part, exc)
            return None

    def _rels(self, part: str) -> list[tuple[str, str, str, str]]:
        folder, base = posixpath.split(part)
        rels_part = posixpath.join(folder, "_rels", base + ".rels")
        root = self._optional_xml(rels_part)
        if root is None:
            return []
        result = []
        for rel in root.findall("rel:Relationship", NS):
            target = rel.get("Target", "")
            mode = rel.get("TargetMode", "Internal")
            if mode != "External":
                target = target.lstrip("/") if target.startswith("/") else \
                    posixpath.normpath(posixpath.join(folder, target))
            result.append((rel.get("Id", ""), rel.get("Type", ""), target, mode))
        return result

    def _main_part(self) -> str:
        for _, rel_type, target, _ in self._rels(""):
            if rel_type.endswith(REL_OFFICE_DOC) and target in self.names:
                return target
        if "word/document.xml" in self.names:
            return "word/document.xml"
        raise DocxParseError("Not a valid DOCX file: the main document part is missing.")

    # ---- entry point ----------------------------------------------------
    def run(self) -> DocumentContext:
        main = self._main_part()
        try:
            root = self._xml(main)
        except etree.XMLSyntaxError as exc:
            raise DocxParseError(f"The main document XML is corrupt: {exc}") from exc
        if root.tag.startswith("{%s}" % STRICT_W_NS):
            raise DocxParseError("Strict Open XML is not supported. Save it as a standard .docx.")
        if root.tag != W + "document":
            raise DocxParseError("Not a Word document: unexpected root element.")

        rels = self._rels(main)
        folder = posixpath.dirname(main)
        by_type = {}
        for _, rel_type, target, _ in rels:
            by_type.setdefault(rel_type.rsplit("/", 1)[-1], []).append(target)

        self._load_theme(by_type.get("theme", [posixpath.join(folder, "theme/theme1.xml")]))
        self._load_styles(by_type.get("styles", [posixpath.join(folder, "styles.xml")]))
        self._load_settings(root, by_type.get("settings", []))
        self._load_metadata()
        self._load_comments(by_type.get("comments", []))

        body = root.find(W + "body")
        if body is None:
            raise DocxParseError("Not a valid DOCX file: the document body is missing.")
        state = _WalkState(part=posixpath.basename(main), container="body",
                           rels=self._rel_map(rels))
        self._walk(body, state)

        for container, rel_name in (("header", "header"), ("footer", "footer"),
                                    ("footnote", "footnotes"), ("endnote", "endnotes")):
            for target in by_type.get(rel_name, []):
                self._walk_secondary(target, container)

        self._collect_document_facts(root)
        return self.context

    @staticmethod
    def _rel_map(rels) -> dict[str, str]:
        return {rel_id: target for rel_id, _, target, _ in rels}

    def _walk_secondary(self, part: str, container: str) -> None:
        root = self._optional_xml(part, key=container)
        if root is None:
            return
        rels = self._rel_map(self._rels(part))
        state = _WalkState(part=posixpath.basename(part), container=container, rels=rels)
        saved = self.current_section
        self.current_section = None
        if container in ("footnote", "endnote"):
            for note in root:
                if note.get(W + "type") in (None, "normal"):
                    self._walk(note, state)
        else:
            self._walk(root, state)
        self.current_section = saved

    # ---- theme, styles, settings, metadata ------------------------------
    def _load_theme(self, candidates: list[str]) -> None:
        for part in candidates:
            root = self._optional_xml(part, key="theme")
            if root is None:
                continue
            scheme = root.find(".//a:clrScheme", NS)
            if scheme is None:
                continue
            for slot in scheme:
                name = etree.QName(slot).localname
                srgb = slot.find("a:srgbClr", NS)
                system = slot.find("a:sysClr", NS)
                if srgb is not None:
                    self.theme[name] = srgb.get("val", "").upper()
                elif system is not None:
                    self.theme[name] = system.get("lastClr", "").upper()

    def _theme_color(self, name: str | None) -> str | None:
        if not name:
            return None
        return self.theme.get(THEME_ALIASES.get(name, name))

    def _fill(self, shd) -> str | None:
        if shd is None:
            return None
        fill = shd.get(W + "fill")
        if fill and _HEX.match(fill):
            return fill.upper()
        return self._theme_color(shd.get(W + "themeFill"))

    def _rpr_props(self, rpr) -> dict:
        props: dict = {}
        if rpr is None:
            return props
        for tag, key in (("b", "bold"), ("i", "italic"), ("caps", "caps"), ("vanish", "hidden")):
            el = rpr.find(W + tag)
            if el is not None:
                props[key] = _on(el)
        underline = rpr.find(W + "u")
        if underline is not None:
            props["underline"] = underline.get(W + "val") not in (None, "none")
        size = rpr.find(W + "sz")
        if size is not None:
            try:
                props["size_pt"] = int(size.get(W + "val")) / 2
            except (TypeError, ValueError):
                pass
        color = rpr.find(W + "color")
        if color is not None:
            value = color.get(W + "val")
            if value and _HEX.match(value):
                props["color"] = value.upper()
            elif value == "auto":
                props["color"] = None
            else:
                props["color"] = self._theme_color(color.get(W + "themeColor"))
        highlight = rpr.find(W + "highlight")
        if highlight is not None:
            props["highlight"] = HIGHLIGHT_HEX.get(highlight.get(W + "val"))
        shading = self._fill(rpr.find(W + "shd"))
        if shading:
            props["shading"] = shading
        vert = rpr.find(W + "vertAlign")
        if vert is not None:
            props["vert_align"] = vert.get(W + "val")
        lang = rpr.find(W + "lang")
        if lang is not None and lang.get(W + "val"):
            props["lang"] = lang.get(W + "val")
        return props

    def _ppr_props(self, ppr) -> dict:
        props: dict = {}
        if ppr is None:
            return props
        outline = ppr.find(W + "outlineLvl")
        if outline is not None:
            try:
                props["outline"] = int(outline.get(W + "val"))
            except (TypeError, ValueError):
                pass
        jc = ppr.find(W + "jc")
        if jc is not None:
            props["jc"] = jc.get(W + "val")
        num_id = ppr.find(W + "numPr/" + W + "numId")
        if num_id is not None:
            props["num_id"] = num_id.get(W + "val")
        fill = self._fill(ppr.find(W + "shd"))
        if fill:
            props["shading"] = fill
        return props

    def _load_styles(self, candidates: list[str]) -> None:
        for part in candidates:
            root = self._optional_xml(part, key="styles")
            if root is None:
                continue
            defaults = root.find(W + "docDefaults")
            if defaults is not None:
                self.default_rpr = self._rpr_props(
                    defaults.find(W + "rPrDefault/" + W + "rPr"))
                self.default_ppr = self._ppr_props(
                    defaults.find(W + "pPrDefault/" + W + "pPr"))
            raw: dict[str, _Style] = {}
            for style in root.findall(W + "style"):
                style_id = style.get(W + "styleId")
                if not style_id:
                    continue
                name_el = style.find(W + "name")
                based = style.find(W + "basedOn")
                style_type = style.get(W + "type", "paragraph")
                has_shading = style_type == "table" and any(
                    (self._fill(shd) or "FFFFFF") != "FFFFFF"
                    for shd in style.iter(W + "shd"))
                raw[style_id] = _Style(
                    style_id=style_id,
                    name=name_el.get(W + "val", "") if name_el is not None else "",
                    type=style_type,
                    based_on=based.get(W + "val") if based is not None else None,
                    rpr=self._rpr_props(style.find(W + "rPr")),
                    ppr=self._ppr_props(style.find(W + "pPr")),
                    has_shading=has_shading,
                )
                if style_type == "paragraph" and style.get(W + "default") in ("1", "true", "on"):
                    self.default_paragraph_style = style_id
            self.styles = {sid: self._resolve_style(sid, raw) for sid in raw}
            # A Normal style language counts as the document's default language.
            default_style = self.styles.get(self.default_paragraph_style or "")
            language = self.default_rpr.get("lang") or (
                default_style.rpr.get("lang") if default_style else None)
            self.context.metadata.default_language = language or ""
            return

    @staticmethod
    def _resolve_style(style_id: str, raw: dict[str, _Style]) -> _Style:
        chain, seen = [], set()
        current: str | None = style_id
        while current and current in raw and current not in seen:
            seen.add(current)
            chain.append(raw[current])
            current = raw[current].based_on
        rpr, ppr = {}, {}
        for style in reversed(chain):
            rpr.update(style.rpr)
            ppr.update(style.ppr)
        own = raw[style_id]
        return _Style(own.style_id, own.name, own.type, own.based_on, rpr, ppr,
                      any(style.has_shading for style in chain))

    def _load_settings(self, root, candidates: list[str]) -> None:
        background = root.find(W + "background")
        for part in candidates:
            settings = self._optional_xml(part, key="settings")
            if settings is None:
                continue
            if background is not None and settings.find(W + "displayBackgroundShape") is not None:
                color = background.get(W + "color")
                if color and _HEX.match(color):
                    self.page_background = color.upper()

    def _load_metadata(self) -> None:
        meta = self.context.metadata
        core = self._optional_xml("docProps/core.xml", key="core")
        if core is not None:
            def text(path: str) -> str:
                el = core.find(path, NS)
                return (el.text or "").strip() if el is not None else ""
            meta.title = text("dc:title")
            meta.author = text("dc:creator")
            meta.subject = text("dc:subject")
            meta.keywords = text("cp:keywords")
            meta.core_language = text("dc:language")
        app = self._optional_xml("docProps/app.xml", key="app")
        if app is not None:
            application = app.find("ep:Application", NS)
            pages = app.find("ep:Pages", NS)
            meta.application = (application.text or "") if application is not None else ""
            if pages is not None and (pages.text or "").strip().isdigit():
                meta.pages_reported = int(pages.text)

    def _load_comments(self, candidates: list[str]) -> None:
        for part in candidates:
            root = self._optional_xml(part, key="comments")
            if root is not None:
                self.context.comments += len(root.findall(W + "comment"))

    def _collect_document_facts(self, root) -> None:
        ctx = self.context
        ctx.tracked_changes = sum(
            1 for tag in ("ins", "del", "moveFrom", "moveTo") for _ in root.iter(W + tag))
        instructions = [el.text or "" for el in root.iter(W + "instrText")]
        instructions += [el.get(W + "instr", "") for el in root.iter(W + "fldSimple")]
        galleries = [el.get(W + "val", "") for el in root.iter(W + "docPartGallery")]
        ctx.has_toc = any(_TOC_FIELD.search(text) for text in instructions) or any(
            "table of contents" in gallery.lower() for gallery in galleries)
        for index, sect in enumerate(root.iter(W + "sectPr")):
            cols = sect.find(W + "cols")
            try:
                count = int(cols.get(W + "num", "1")) if cols is not None else 1
            except ValueError:
                count = 1
            ctx.sections.append(SectionInfo(index=index, columns=count))
        ctx.word_count = sum(len(p.text.split()) for p in ctx.paragraphs)

    # ---- tree walk ------------------------------------------------------
    def _walk(self, container, state: _WalkState) -> None:
        for child in container:
            if not isinstance(child.tag, str):
                continue
            tag = child.tag
            if tag == W + "p":
                self._paragraph(child, state)
            elif tag == W + "tbl":
                self._table(child, state)
            elif tag == W + "sdt":
                content = child.find(W + "sdtContent")
                if content is not None:
                    self._walk(content, state)
            elif tag in (W + "customXml", W + "ins", W + "moveTo", W + "smartTag"):
                self._walk(child, state)
            elif tag == MC + "AlternateContent":
                choice = child.find(MC + "Choice")
                if choice is not None:
                    self._walk(choice, state)

    def _iter_runs(self, parent, hyperlink_sink: list | None = None):
        for child in parent:
            if not isinstance(child.tag, str):
                continue
            tag = child.tag
            if tag == W + "r":
                yield child
            elif tag == W + "hyperlink":
                if hyperlink_sink is not None:
                    hyperlink_sink.append(child)
                yield from self._iter_runs(child)
            elif tag in (W + "ins", W + "moveTo", W + "smartTag", W + "customXml", W + "fldSimple"):
                yield from self._iter_runs(child, hyperlink_sink)
            elif tag == W + "sdt":
                content = child.find(W + "sdtContent")
                if content is not None:
                    yield from self._iter_runs(content, hyperlink_sink)
            elif tag == MC + "AlternateContent":
                choice = child.find(MC + "Choice")
                if choice is not None:
                    yield from self._iter_runs(choice, hyperlink_sink)

    @staticmethod
    def _run_text(run) -> str:
        parts = []
        for child in run:
            if child.tag == W + "t":
                parts.append(child.text or "")
            elif child.tag == W + "tab":
                parts.append("\t")
            elif child.tag in (W + "br", W + "cr"):
                if child.get(W + "type") != "page":
                    parts.append("\n")
            elif child.tag == W + "noBreakHyphen":
                parts.append("-")
        return "".join(parts)

    def _heading_level(self, style: _Style | None, direct: dict) -> int | None:
        if "outline" in direct:
            return direct["outline"] + 1 if direct["outline"] < 9 else None
        if style is None:
            return None
        match = _HEADING_NAME.match(style.name.strip())
        if match:
            return int(match.group(1))
        outline = style.ppr.get("outline")
        return outline + 1 if outline is not None and outline < 9 else None

    def _paragraph(self, element, state: _WalkState) -> None:
        ppr = element.find(W + "pPr")
        direct = self._ppr_props(ppr)
        style_el = ppr.find(W + "pStyle") if ppr is not None else None
        style_id = style_el.get(W + "val") if style_el is not None else self.default_paragraph_style
        style = self.styles.get(style_id or "")
        merged_ppr = {**self.default_ppr, **(style.ppr if style else {}), **direct}
        num_id = merged_ppr.get("num_id")

        info = ParagraphInfo(
            index=len(self.context.paragraphs), part=state.part, container=state.container,
            style_id=style_id, style_name=style.name if style else None,
            is_list=bool(num_id and num_id != "0"), justification=merged_ppr.get("jc"),
            has_section_break=ppr is not None and ppr.find(W + "sectPr") is not None,
            table_index=state.table_index,
        )
        self.context.paragraphs.append(info)

        para_rpr = {**self.default_rpr, **(style.rpr if style else {})}
        links: list = []
        texts: list[str] = []
        for run in self._iter_runs(element, links):
            info_run = self._run(run, para_rpr, merged_ppr, state)
            texts.append(info_run.text)
            if info_run.text:
                info.runs.append(info_run)
            if run.find(W + "br[@" + W + "type='page']") is not None:
                info.has_page_break = True
            # Word writes lastRenderedPageBreak as a hint only, so it is ignored here.
            if self._run_objects(run, state):
                info.has_drawing = True
        info.text = "".join(texts)

        if state.container in ("body", "table"):
            info.heading_level = self._heading_level(style, direct)
        info.section = self.current_section
        if info.heading_level is not None and info.text.strip():
            self.current_section = info.text.strip()
            info.section = self.current_section

        for link in links:
            rel_id = link.get(R + "id")
            self.context.hyperlinks.append(HyperlinkInfo(
                text="".join(self._run_text(r) for r in self._iter_runs(link)).strip(),
                target=state.rels.get(rel_id) if rel_id else None,
                anchor=link.get(W + "anchor"), location=info.location,
            ))

    def _run(self, run, para_rpr: dict, para_ppr: dict, state: _WalkState) -> RunInfo:
        rpr = run.find(W + "rPr")
        char_style_el = rpr.find(W + "rStyle") if rpr is not None else None
        char_style = self.styles.get(char_style_el.get(W + "val")) \
            if char_style_el is not None else None
        props = {**para_rpr, **(char_style.rpr if char_style else {}), **self._rpr_props(rpr)}

        explicit = props.get("highlight") or props.get("shading") or para_ppr.get("shading") \
            or state.cell_fill
        known = bool(explicit) or not (state.table_style_shaded or state.container == "textbox")
        return RunInfo(
            text=self._run_text(run),
            bold=props.get("bold", False), italic=props.get("italic", False),
            underline=props.get("underline", False), caps=props.get("caps", False),
            hidden=props.get("hidden", False),
            size_pt=props.get("size_pt", DEFAULT_FONT_SIZE_PT), color=props.get("color"),
            background=explicit or self.page_background, background_known=known,
            vert_align=props.get("vert_align"), lang=props.get("lang"),
        )

    # ---- images, shapes and text boxes ----------------------------------
    def _run_objects(self, run, state: _WalkState) -> bool:
        found = False
        for child in run:
            if child.tag == W + "drawing":
                found |= self._drawing(child, state)
            elif child.tag == MC + "AlternateContent":
                # Choice and Fallback describe one object, so only Choice is read.
                choice = child.find(MC + "Choice")
                if choice is not None:
                    for sub in choice:
                        if sub.tag == W + "drawing":
                            found |= self._drawing(sub, state)
                        elif sub.tag in (W + "pict", W + "object"):
                            found |= self._vml(sub, state)
            elif child.tag in (W + "pict", W + "object"):
                found |= self._vml(child, state)
        return found

    def _drawing(self, drawing, state: _WalkState) -> bool:
        holder = drawing.find(WP + "inline")
        floating = False
        if holder is None:
            holder = drawing.find(WP + "anchor")
            floating = holder is not None
        if holder is None:
            return False
        doc_pr = holder.find(WP + "docPr")
        data = holder.find(A + "graphic/" + A + "graphicData")
        uri = data.get("uri", "") if data is not None else ""
        boxes = list(holder.iter(W + "txbxContent"))
        if boxes and "wpg" not in uri:
            self._text_boxes(boxes, state, floating)
            return True

        kind = "shape"
        if uri.endswith("/picture"):
            kind = "picture"
        elif uri.endswith("/chart"):
            kind = "chart"
        elif uri.endswith("/diagram"):
            kind = "diagram"
        elif "wordprocessingGroup" in uri:
            kind = "group"
        blip = holder.find(".//" + A + "blip")
        embed = blip.get(R + "embed") if blip is not None else None

        decorative = False
        if doc_pr is not None:
            for el in doc_pr.iter():
                if isinstance(el.tag, str) and etree.QName(el).localname == "decorative":
                    decorative = el.get("val") in ("1", "true")

        self.context.images.append(ImageInfo(
            index=len(self.context.images), kind=kind, part=state.part,
            container=state.container,
            alt=(doc_pr.get("descr", "") if doc_pr is not None else "").strip(),
            title=(doc_pr.get("title", "") if doc_pr is not None else "").strip(),
            name=(doc_pr.get("name", "") if doc_pr is not None else ""),
            target=state.rels.get(embed) if embed else None,
            decorative=decorative, floating=floating, section=self.current_section,
        ))
        if boxes:
            self._text_boxes(boxes, state, floating)
        return True

    def _vml(self, element, state: _WalkState) -> bool:
        boxes = list(element.iter(W + "txbxContent"))
        if boxes:
            self._text_boxes(boxes, state, floating=True)
            return True
        found = False
        for shape in element.iter(V + "shape"):
            image = shape.find(V + "imagedata")
            if image is None:
                continue
            rel_id = image.get(R + "id") or image.get(R + "pict")
            style = shape.get("style", "")
            self.context.images.append(ImageInfo(
                index=len(self.context.images),
                kind="ole" if element.tag == W + "object" else "vml",
                part=state.part, container=state.container,
                alt=(shape.get("alt") or "").strip(), name=shape.get("id", ""),
                target=state.rels.get(rel_id) if rel_id else None,
                floating="position:absolute" in style.replace(" ", ""),
                section=self.current_section,
            ))
            found = True
        return found

    def _text_boxes(self, boxes, state: _WalkState, floating: bool) -> None:
        inner = _WalkState(part=state.part, container="textbox", rels=state.rels)
        for box in boxes:
            start = len(self.context.paragraphs)
            self._walk(box, inner)
            text = " ".join(p.text.strip() for p in self.context.paragraphs[start:]
                            if p.text.strip())
            self.context.text_boxes.append(TextBoxInfo(
                index=len(self.context.text_boxes), text=text, part=state.part,
                floating=floating, section=self.current_section))

    # ---- tables ---------------------------------------------------------
    def _table(self, element, state: _WalkState) -> None:
        props = element.find(W + "tblPr")
        style_el = props.find(W + "tblStyle") if props is not None else None
        style_id = style_el.get(W + "val") if style_el is not None else None
        style = self.styles.get(style_id or "")
        caption = props.find(W + "tblCaption") if props is not None else None
        description = props.find(W + "tblDescription") if props is not None else None

        table = TableInfo(
            index=len(self.context.tables), part=state.part, container=state.container,
            depth=state.table_depth, style_id=style_id,
            caption=(caption.get(W + "val", "") if caption is not None else "").strip(),
            description=(description.get(W + "val", "") if description is not None else "").strip(),
            section=self.current_section,
        )
        self.context.tables.append(table)

        inner = _WalkState(
            part=state.part, container="table" if state.container == "body" else state.container,
            rels=state.rels, table_index=table.index, table_depth=state.table_depth + 1,
            table_style_shaded=bool(style and style.has_shading) or state.table_style_shaded,
        )

        rows = list(self._iter_rows(element))
        table.rows = len(rows)
        column_filled: dict[int, bool] = {}
        for row_index, row in enumerate(rows):
            row_props = row.find(W + "trPr")
            if row_index == 0 and row_props is not None:
                table.has_header_row = _on(row_props.find(W + "tblHeader"))
            position, row_filled = 0, False
            for cell in self._iter_cells(row):
                cell_props = cell.find(W + "tcPr")
                span, merged = 1, False
                if cell_props is not None:
                    span_el = cell_props.find(W + "gridSpan")
                    if span_el is not None:
                        try:
                            span = max(1, int(span_el.get(W + "val", "1")))
                        except ValueError:
                            span = 1
                        merged = span > 1
                    merged = merged or cell_props.find(W + "vMerge") is not None
                    inner.cell_fill = self._fill(cell_props.find(W + "shd"))
                else:
                    inner.cell_fill = None
                if merged:
                    table.merged_cells += 1

                start = len(self.context.paragraphs)
                self._walk(cell, inner)
                filled = any(
                    p.text.strip() or p.has_drawing
                    for p in self.context.paragraphs[start:]) or cell.find(W + "tbl") is not None
                row_filled = row_filled or filled
                for column in range(position, position + span):
                    column_filled[column] = column_filled.get(column, False) or filled
                position += span
            if not row_filled:
                table.blank_rows += 1
        grid = element.find(W + "tblGrid")
        grid_columns = len(grid.findall(W + "gridCol")) if grid is not None else 0
        table.columns = max(grid_columns, len(column_filled))
        table.blank_columns = sum(1 for filled in column_filled.values() if not filled)

    def _iter_rows(self, element):
        for child in element:
            if child.tag == W + "tr":
                yield child
            elif child.tag == W + "sdt":
                content = child.find(W + "sdtContent")
                if content is not None:
                    yield from self._iter_rows(content)

    def _iter_cells(self, row):
        for child in row:
            if child.tag == W + "tc":
                yield child
            elif child.tag == W + "sdt":
                content = child.find(W + "sdtContent")
                if content is not None:
                    yield from self._iter_cells(content)
