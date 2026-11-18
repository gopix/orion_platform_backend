"""Audit-sheet workbook writer and reader.

The audit sheet is the structural review artifact: the system proposes the
unit -> chapter breakdown it read out of the syllabus, and the SME confirms or
corrects it before any blueprint is generated. This module owns the workbook
*format* only — persistence and versioning live in ``audit_sheet_service``.

The same column constants drive both ``build_workbook`` and ``read_submission``,
so a change to the layout cannot silently desynchronise the writer from the
parser.

Editable (yellow) columns are the only ones the reader looks at. Everything else
is reference or formula, so a user who edits nothing but the yellow cells always
produces a readable submission.
"""
from __future__ import annotations

import json
from io import BytesIO
from typing import Any, Dict, List, Optional

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

# --- workbook identity -------------------------------------------------------
# Written into README so a submitted file can be matched back to the exact
# generated version it came from. Scanned for by label rather than read from a
# fixed cell, so cosmetic edits to README do not break the round-trip.
SHEET_ID_LABEL = "BOOKFORGE_SHEET_ID"

SHEET_README = "README"
SHEET_CHAPTERS = "Chapters"
SHEET_UNITS = "Unit Summary"
SHEET_MATCHES = "PYQ Matches"
SHEET_FLAGS = "Parse Flags"

# --- Chapters tab layout -----------------------------------------------------
# (column index, header, width). Index is 1-based to match openpyxl.
COL_SECTION = 1
COL_UNIT_NO = 2
COL_UNIT = 3
COL_CH_NO = 4
COL_CHAPTER = 5
COL_PYQ_HITS = 6
COL_PYQ_YEARS = 7
COL_ADVISORY = 8
COL_KEEP = 9
COL_CORRECTED = 10
COL_WEIGHT = 11
COL_NOTES = 12

CHAPTER_COLUMNS = [
    (COL_SECTION, "Section", 20),
    (COL_UNIT_NO, "Unit #", 7),
    (COL_UNIT, "Unit", 32),
    (COL_CH_NO, "Ch #", 6),
    (COL_CHAPTER, "Chapter (proposed)", 52),
    (COL_PYQ_HITS, "PYQ hits (ref)", 12),
    (COL_PYQ_YEARS, "PYQ years", 20),
    (COL_ADVISORY, "PYQ advisory band", 15),
    (COL_KEEP, "Keep? (Y/N)", 11),
    (COL_CORRECTED, "Corrected chapter title", 42),
    (COL_WEIGHT, "SME weight (1-5)", 13),
    (COL_NOTES, "SME notes", 42),
]
# The only columns the reader consumes.
EDITABLE_COLUMNS = (COL_KEEP, COL_CORRECTED, COL_WEIGHT, COL_NOTES)

# Freeze to the RIGHT of the chapter title so the title stays on screen while the
# user scrolls out to the weight columns. Freezing earlier hides the one column
# they need most.
CHAPTERS_FREEZE = "F2"

_FONT = "Arial"
_HEAD_FONT = Font(name=_FONT, size=10, bold=True, color="FFFFFF")
_HEAD_FILL = PatternFill("solid", fgColor="1F3864")
_BODY = Font(name=_FONT, size=10)
_BOLD = Font(name=_FONT, size=10, bold=True)
_ITALIC = Font(name=_FONT, size=9, italic=True, color="595959")
_FILL_IN = PatternFill("solid", fgColor="FFFF00")
_REF = PatternFill("solid", fgColor="F2F2F2")
_thin = Side(style="thin", color="BFBFBF")
_BOX = Border(left=_thin, right=_thin, top=_thin, bottom=_thin)
_WRAP = Alignment(wrap_text=True, vertical="top")
_CTR = Alignment(horizontal="center", vertical="center")
_HEAD_ALIGN = Alignment(wrap_text=True, horizontal="center", vertical="center")


def _header_row(ws, columns) -> None:
    for index, header, width in columns:
        cell = ws.cell(1, index, header)
        cell.font = _HEAD_FONT
        cell.fill = _HEAD_FILL
        cell.border = _BOX
        cell.alignment = _HEAD_ALIGN
        ws.column_dimensions[get_column_letter(index)].width = width
    ws.row_dimensions[1].height = 30


def build_workbook(
    *,
    project_id: int,
    version: int,
    generated_at: str,
    chapters: List[Dict[str, Any]],
    project_title: Optional[str] = None,
    flags: Optional[List[Dict[str, Any]]] = None,
    matches: Optional[List[Dict[str, Any]]] = None,
    pyq_source_note: Optional[str] = None,
) -> bytes:
    """Render the audit workbook and return it as ``.xlsx`` bytes.

    ``chapters`` rows use the keys: ``section``, ``unit_number``, ``unit``,
    ``chapter_number``, ``chapter``, ``pyq_hits``, ``pyq_years``.
    """
    flags = flags or []
    matches = matches or []
    wb = Workbook()

    # ---------------------------------------------------------------- README --
    ws = wb.active
    ws.title = SHEET_README
    ws.column_dimensions["A"].width = 3
    ws.column_dimensions["B"].width = 28
    ws.column_dimensions["C"].width = 96

    ws.cell(2, 2, "Book Blueprint — Structure Audit Sheet").font = Font(
        name=_FONT, size=15, bold=True, color="1F3864"
    )
    ws.cell(3, 2, project_title or f"Project {project_id}").font = _ITALIC

    row = 5
    guidance = [
        (
            "What to do",
            "1) Check the unit -> chapter split on the 'Chapters' tab.  "
            "2) Mark 'Keep? (Y/N)' = N for anything that is not a real chapter.  "
            "3) Put the right wording in 'Corrected chapter title' where ours is wrong.  "
            "4) Set 'SME weight (1-5)'.  5) Use 'SME notes' for anything missing or mis-scoped.",
        ),
        (
            "Only yellow cells",
            "Everything else is reference or calculated. You do not need to edit "
            "any non-yellow cell, and the upload only reads the yellow ones.",
        ),
        (
            "Weights are yours",
            "PYQ counts are a REFERENCE signal, not the weighting. The 'PYQ advisory "
            "band' is derived arithmetically from the hit count and is shown only for "
            "comparison — your weight overrides it.",
        ),
        (
            "A zero PYQ count",
            "means 'not found in the supplied previous-year questions', NOT "
            "'unimportant'. Leave the weight blank if you want it held for later.",
        ),
        (
            "Check our matching",
            "The 'PYQ Matches' tab lists every question we matched to a chapter. "
            "Matching is automated and will contain mistakes — please spot-check it.",
        ),
    ]
    if pyq_source_note:
        guidance.append(("PYQ source", pyq_source_note))

    for label, text in guidance:
        ws.cell(row, 2, label).font = _BOLD
        cell = ws.cell(row, 3, text)
        cell.font = _BODY
        cell.alignment = _WRAP
        row += 1

    row += 1
    ws.cell(row, 2, "Example of a completed row").font = Font(
        name=_FONT, size=11, bold=True
    )
    row += 1
    example_headers = [
        "Chapter (proposed)",
        "Keep? (Y/N)",
        "Corrected chapter title",
        "SME weight (1-5)",
        "SME notes",
    ]
    example_values = [
        "Plate tectonics",
        "Y",
        "",
        5,
        "Core theory — asked far more often in the Optional paper than the "
        "reference count suggests. Weight up.",
    ]
    for offset, header in enumerate(example_headers):
        cell = ws.cell(row, 2 + offset, header)
        cell.font = _HEAD_FONT
        cell.fill = _HEAD_FILL
        cell.border = _BOX
        cell.alignment = _HEAD_ALIGN
    for offset, value in enumerate(example_values):
        cell = ws.cell(row + 1, 2 + offset, value)
        cell.font = _BODY
        cell.border = _BOX
        cell.alignment = _WRAP
        if offset >= 1:
            cell.fill = _FILL_IN
    ws.row_dimensions[row + 1].height = 30

    # Machine-readable identity. Keep it last so it never pushes guidance down.
    row += 4
    ws.cell(row, 2, SHEET_ID_LABEL).font = _ITALIC
    ws.cell(
        row,
        3,
        json.dumps(
            {
                "project_id": project_id,
                "version": version,
                "generated_at": generated_at,
                "chapter_rows": len(chapters),
            }
        ),
    ).font = _ITALIC
    ws.cell(row + 1, 2, "Do not edit the line above").font = _ITALIC
    ws.cell(
        row + 1,
        3,
        "It identifies which generated version this file came from, so your "
        "upload can be matched back to it.",
    ).font = _ITALIC

    # -------------------------------------------------------------- Chapters --
    ws = wb.create_sheet(SHEET_CHAPTERS)
    _header_row(ws, CHAPTER_COLUMNS)
    ws.freeze_panes = CHAPTERS_FREEZE

    row = 2
    for entry in chapters:
        values = {
            COL_SECTION: entry.get("section"),
            COL_UNIT_NO: entry.get("unit_number"),
            COL_UNIT: entry.get("unit"),
            COL_CH_NO: entry.get("chapter_number"),
            COL_CHAPTER: entry.get("chapter"),
            COL_PYQ_HITS: entry.get("pyq_hits", 0),
            COL_PYQ_YEARS: entry.get("pyq_years") or "—",
        }
        for index, value in values.items():
            cell = ws.cell(row, index, value)
            cell.font = _BODY
            cell.border = _BOX
            cell.fill = _REF
            if index in (COL_UNIT_NO, COL_CH_NO, COL_PYQ_HITS):
                cell.alignment = _CTR
            elif index in (COL_CHAPTER, COL_PYQ_YEARS):
                cell.alignment = _WRAP
        # Advisory band recalculates from the hit count; reference only.
        band = ws.cell(
            row,
            COL_ADVISORY,
            "=IF({col}{r}=0,\"—\",IF({col}{r}<=2,2,IF({col}{r}<=5,3,"
            "IF({col}{r}<=9,4,5))))".format(
                col=get_column_letter(COL_PYQ_HITS), r=row
            ),
        )
        band.font = _BODY
        band.fill = _REF
        band.border = _BOX
        band.alignment = _CTR
        # Default 'Keep? = Y' so the SME only has to mark the exceptions.
        keep = ws.cell(row, COL_KEEP, "Y")
        keep.alignment = _CTR
        for index in EDITABLE_COLUMNS:
            cell = ws.cell(row, index)
            cell.font = _BODY
            cell.border = _BOX
            cell.fill = _FILL_IN
            if index == COL_NOTES or index == COL_CORRECTED:
                cell.alignment = _WRAP
            elif index == COL_WEIGHT:
                cell.alignment = _CTR
        row += 1

    last = row - 1
    if last >= 2:
        ws.cell(row, COL_CHAPTER, "TOTAL").font = _BOLD
        total_hits = ws.cell(
            row,
            COL_PYQ_HITS,
            f"=SUM({get_column_letter(COL_PYQ_HITS)}2:"
            f"{get_column_letter(COL_PYQ_HITS)}{last})",
        )
        total_hits.font = _BOLD
        total_hits.alignment = _CTR
        weighted = ws.cell(
            row,
            COL_WEIGHT,
            f"=COUNT({get_column_letter(COL_WEIGHT)}2:"
            f"{get_column_letter(COL_WEIGHT)}{last})",
        )
        weighted.font = _BOLD
        weighted.alignment = _CTR
        ws.cell(
            row, COL_NOTES, "<- chapters you have weighted so far"
        ).font = _ITALIC

    # ---------------------------------------------------------- Unit Summary --
    ws = wb.create_sheet(SHEET_UNITS)
    unit_columns = [
        (1, "Section", 20),
        (2, "Unit", 38),
        (3, "Chapters in unit", 15),
        (4, "PYQ hits (ref)", 13),
        (5, "Chapters with 0 hits", 17),
        (6, "Mean SME weight", 15),
    ]
    _header_row(ws, unit_columns)

    seen: List[tuple] = []
    for entry in chapters:
        key = (entry.get("section"), entry.get("unit"))
        if key not in seen:
            seen.append(key)

    row = 2
    hits_col = get_column_letter(COL_PYQ_HITS)
    unit_col = get_column_letter(COL_UNIT)
    weight_col = get_column_letter(COL_WEIGHT)
    for section, unit in seen:
        ws.cell(row, 1, section).font = _BODY
        ws.cell(row, 2, unit).font = _BODY
        formulas = {
            3: f"=COUNTIFS({SHEET_CHAPTERS}!{unit_col}:{unit_col},B{row})",
            4: f"=SUMIFS({SHEET_CHAPTERS}!{hits_col}:{hits_col},"
            f"{SHEET_CHAPTERS}!{unit_col}:{unit_col},B{row})",
            5: f"=COUNTIFS({SHEET_CHAPTERS}!{unit_col}:{unit_col},B{row},"
            f"{SHEET_CHAPTERS}!{hits_col}:{hits_col},0)",
            6: f'=IFERROR(ROUND(AVERAGEIFS({SHEET_CHAPTERS}!{weight_col}:{weight_col},'
            f'{SHEET_CHAPTERS}!{unit_col}:{unit_col},B{row}),1),"—")',
        }
        for index, formula in formulas.items():
            cell = ws.cell(row, index, formula)
            cell.font = _BODY
            cell.alignment = _CTR
            cell.border = _BOX
        for index in (1, 2):
            ws.cell(row, index).border = _BOX
        row += 1

    if row > 2:
        ws.cell(row, 2, "TOTAL").font = _BOLD
        for index in (3, 4, 5):
            letter = get_column_letter(index)
            cell = ws.cell(row, index, f"=SUM({letter}2:{letter}{row - 1})")
            cell.font = _BOLD
            cell.alignment = _CTR

    # ---------------------------------------------------------- PYQ Matches --
    ws = wb.create_sheet(SHEET_MATCHES)
    match_columns = [
        (1, "Unit", 28),
        (2, "Chapter", 42),
        (3, "Year", 8),
        (4, "Matched question", 96),
        (5, "Correct match? (Y/N)", 16),
    ]
    _header_row(ws, match_columns)
    ws.freeze_panes = "A2"
    row = 2
    for match in matches:
        values = [
            match.get("unit"),
            match.get("chapter"),
            match.get("year"),
            match.get("text"),
        ]
        for index, value in enumerate(values, start=1):
            cell = ws.cell(row, index, value)
            cell.font = _BODY
            cell.border = _BOX
            cell.alignment = _CTR if index == 3 else _WRAP
            if index <= 3:
                cell.fill = _REF
        verdict = ws.cell(row, 5)
        verdict.fill = _FILL_IN
        verdict.border = _BOX
        verdict.alignment = _CTR
        row += 1
    if not matches:
        ws.cell(2, 1, "No PYQ matches were produced for this project.").font = _ITALIC

    # ----------------------------------------------------------- Parse Flags --
    ws = wb.create_sheet(SHEET_FLAGS)
    _header_row(
        ws,
        [
            (1, "Unit", 38),
            (2, "Issue", 28),
            (3, "Text as written in the source", 84),
            (4, "Correct? (Y/N)", 14),
        ],
    )
    row = 2
    for flag in flags:
        for index, value in enumerate(
            [flag.get("unit"), flag.get("reason"), flag.get("segment")], start=1
        ):
            cell = ws.cell(row, index, value)
            cell.font = _BODY
            cell.border = _BOX
            cell.alignment = _WRAP
        verdict = ws.cell(row, 4)
        verdict.fill = _FILL_IN
        verdict.border = _BOX
        verdict.alignment = _CTR
        row += 1
    if not flags:
        ws.cell(2, 1, "No parsing ambiguities were flagged.").font = _ITALIC
    else:
        ws.cell(
            row + 1,
            1,
            "These are places where the source's own punctuation was ambiguous, so "
            "we had to guess where one chapter ends and the next begins. Please "
            "confirm each split.",
        ).font = _ITALIC

    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def read_sheet_identity(data: bytes) -> Optional[Dict[str, Any]]:
    """Return the identity block written into README, or None if absent.

    Used to match an uploaded workbook back to the generated version it came
    from, so a submission can never be attributed to the wrong version.
    """
    workbook = load_workbook(BytesIO(data), data_only=True, read_only=True)
    try:
        if SHEET_README not in workbook.sheetnames:
            return None
        sheet = workbook[SHEET_README]
        for row in sheet.iter_rows(min_col=1, max_col=4):
            for cell in row:
                if isinstance(cell.value, str) and cell.value.strip() == SHEET_ID_LABEL:
                    payload = sheet.cell(cell.row, cell.column + 1).value
                    if not payload:
                        return None
                    try:
                        return json.loads(payload)
                    except (TypeError, ValueError):
                        return None
        return None
    finally:
        workbook.close()


def _is_blank(values) -> bool:
    """True when a row has no content in any cell.

    Data tables are terminated by the first blank row, so explanatory footnotes
    written below a table (with a blank row above them) are never mistaken for
    data. Without this, the note under 'Parse Flags' reads back as an extra flag.
    """
    if not values:
        return True
    return all(value is None or str(value).strip() == "" for value in values)


def read_submission(data: bytes) -> Dict[str, Any]:
    """Parse a filled-in audit workbook into structured data.

    Reads only the editable columns, so formulas (which openpyxl writes without
    cached values) are never relied on. Returns::

        {"chapters": [...], "matches": [...], "flags": [...],
         "counts": {"rows": n, "kept": n, "dropped": n, "weighted": n,
                    "retitled": n}}

    Raises ``ValueError`` when the workbook is not an audit sheet at all, so the
    caller can turn that into a 400 rather than a 500.
    """
    workbook = load_workbook(BytesIO(data), data_only=True, read_only=True)
    try:
        if SHEET_CHAPTERS not in workbook.sheetnames:
            raise ValueError(
                f"Workbook has no '{SHEET_CHAPTERS}' sheet — this does not look "
                "like a Book Forge audit sheet."
            )

        sheet = workbook[SHEET_CHAPTERS]
        rows = list(sheet.iter_rows(min_row=2, values_only=True))

        chapters: List[Dict[str, Any]] = []
        for values in rows:
            if _is_blank(values):
                break

            def at(index: int):
                # values is 0-based, our COL_* constants are 1-based.
                position = index - 1
                return values[position] if position < len(values) else None

            proposed = at(COL_CHAPTER)
            # The TOTAL footer reuses the chapter column; skip it and blank rows.
            if not proposed or str(proposed).strip().upper() == "TOTAL":
                continue

            keep_raw = at(COL_KEEP)
            keep = str(keep_raw).strip().upper() if keep_raw is not None else "Y"
            corrected = at(COL_CORRECTED)
            weight_raw = at(COL_WEIGHT)
            try:
                weight = int(weight_raw) if weight_raw not in (None, "") else None
            except (TypeError, ValueError):
                weight = None

            chapters.append(
                {
                    "section": at(COL_SECTION),
                    "unit_number": at(COL_UNIT_NO),
                    "unit": at(COL_UNIT),
                    "chapter_number": at(COL_CH_NO),
                    "proposed_chapter": str(proposed).strip(),
                    # The corrected title wins when supplied; this is the value
                    # blueprint generation should use.
                    "chapter": (
                        str(corrected).strip()
                        if corrected not in (None, "")
                        else str(proposed).strip()
                    ),
                    "was_retitled": corrected not in (None, ""),
                    "keep": keep != "N",
                    "pyq_hits": at(COL_PYQ_HITS),
                    "sme_weight": weight,
                    "sme_notes": at(COL_NOTES),
                }
            )

        matches: List[Dict[str, Any]] = []
        if SHEET_MATCHES in workbook.sheetnames:
            for values in workbook[SHEET_MATCHES].iter_rows(
                min_row=2, values_only=True
            ):
                if _is_blank(values):
                    break
                if not values[0]:
                    continue
                verdict = values[4] if len(values) > 4 else None
                matches.append(
                    {
                        "unit": values[0],
                        "chapter": values[1] if len(values) > 1 else None,
                        "year": values[2] if len(values) > 2 else None,
                        "text": values[3] if len(values) > 3 else None,
                        "is_correct": (
                            None
                            if verdict in (None, "")
                            else str(verdict).strip().upper() != "N"
                        ),
                    }
                )

        flags: List[Dict[str, Any]] = []
        if SHEET_FLAGS in workbook.sheetnames:
            for values in workbook[SHEET_FLAGS].iter_rows(min_row=2, values_only=True):
                if _is_blank(values):
                    break
                if not values[0]:
                    continue
                verdict = values[3] if len(values) > 3 else None
                flags.append(
                    {
                        "unit": values[0],
                        "reason": values[1] if len(values) > 1 else None,
                        "segment": values[2] if len(values) > 2 else None,
                        "is_correct": (
                            None
                            if verdict in (None, "")
                            else str(verdict).strip().upper() != "N"
                        ),
                    }
                )

        kept = [c for c in chapters if c["keep"]]
        return {
            "chapters": chapters,
            "matches": matches,
            "flags": flags,
            "counts": {
                "rows": len(chapters),
                "kept": len(kept),
                "dropped": len(chapters) - len(kept),
                "weighted": len([c for c in chapters if c["sme_weight"] is not None]),
                "retitled": len([c for c in chapters if c["was_retitled"]]),
                "match_verdicts": len(
                    [m for m in matches if m["is_correct"] is not None]
                ),
            },
        }
    finally:
        workbook.close()
