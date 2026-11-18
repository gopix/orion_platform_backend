"""Render a book blueprint (the ``blueprint_json`` payload) into an author-friendly
PDF.

Deliberately dependency-light: it takes a plain ``dict`` and returns PDF bytes,
with no app/DB imports, so it can be reused and unit-tested in isolation. Uses
ReportLab Platypus (the same toolkit as the interview PDF path).

The layout reads like a writing brief, not a data dump — a cover block, then one
section per chapter with summary, topics, objectives, key concepts, focus areas,
and an assessment-plan table.
"""
from datetime import datetime
from io import BytesIO
from typing import Any, Dict, List, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# Fixed, human-readable labels for the assessment question types.
_TYPE_LABELS = {
    "mcq_single_correct": "MCQ (single correct)",
    "multiple_correct": "Multiple correct",
    "numerical_value": "Numerical value",
    "assertion_reason": "Assertion & reason",
    "fill_in_the_blanks": "Fill in the blanks",
    "previous_year_questions": "Previous-year questions",
}
_DIFFICULTY_LABELS = {"easy": "Easy", "medium": "Medium", "hard": "Hard"}

_ACCENT = colors.HexColor("#2f4b7c")
_LIGHT = colors.HexColor("#eef1f6")


def render_blueprint_pdf(
    blueprint: Dict[str, Any],
    *,
    project_title: Optional[str] = None,
    version: Optional[int] = None,
) -> bytes:
    """Render a blueprint dict into PDF bytes."""
    blueprint = blueprint or {}
    styles = _styles()

    title = project_title or blueprint.get("title") or "Book Blueprint"
    chapters = blueprint.get("chapters") or []

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        title=f"{title} — Blueprint",
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    )

    flow: List[Any] = []
    flow += _cover(blueprint, title, version, chapters, styles)
    for chapter in chapters:
        flow += _chapter_block(chapter, styles)

    doc.build(flow, onFirstPage=_footer, onLaterPages=_footer)
    return buffer.getvalue()


# ------------------------------------------------------------------ #
# Sections                                                           #
# ------------------------------------------------------------------ #
def _cover(blueprint, title, version, chapters, styles) -> List[Any]:
    meta_bits = []
    if version is not None:
        meta_bits.append(f"Version {version}")
    meta_bits.append(datetime.now().strftime("%d %b %Y"))
    subtitle = "Book Blueprint  |  Author Brief  |  " + "  |  ".join(meta_bits)

    flow: List[Any] = [
        Paragraph(_esc(title), styles["CoverTitle"]),
        Paragraph(_esc(subtitle), styles["Subtle"]),
        Spacer(1, 6),
        HRFlowable(width="100%", thickness=1, color=_ACCENT),
        Spacer(1, 10),
    ]

    facts = [
        ("Target audience", blueprint.get("target_audience")),
        ("Chapters", str(len(chapters)) if chapters else None),
        ("Estimated length", _pages(blueprint.get("estimated_length"))),
    ]
    facts = [(k, v) for k, v in facts if v]
    if facts:
        table = Table(
            [[Paragraph(f"<b>{_esc(k)}</b>", styles["Small"]),
              Paragraph(_esc(str(v)), styles["Small"])] for k, v in facts],
            colWidths=[45 * mm, None],
            hAlign="LEFT",
        )
        table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
        ]))
        flow.append(table)
        flow.append(Spacer(1, 8))

    if blueprint.get("description"):
        flow.append(Paragraph(_esc(blueprint["description"]), styles["Body"]))
    flow.append(Spacer(1, 14))
    return flow


def _chapter_block(chapter: Dict[str, Any], styles) -> List[Any]:
    if not isinstance(chapter, dict):
        return []
    num = chapter.get("chapter_number")
    heading = f"Chapter {num}: {chapter.get('title', 'Untitled')}" if num else str(
        chapter.get("title", "Untitled")
    )

    flow: List[Any] = [
        HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#c9d2e0")),
        Spacer(1, 6),
        Paragraph(_esc(heading), styles["Chapter"]),
    ]

    chips = []
    if chapter.get("difficulty_level"):
        chips.append(f"Difficulty: {chapter['difficulty_level']}")
    if chapter.get("weight") is not None:
        chips.append(f"Weight: {chapter['weight']}/5")
    plan = chapter.get("assessment_plan") or {}
    if plan.get("total_questions"):
        chips.append(f"{plan['total_questions']} questions")
    if chips:
        flow.append(Paragraph(_esc("     ".join(chips)), styles["Subtle"]))

    if chapter.get("summary"):
        flow.append(Spacer(1, 4))
        flow.append(Paragraph(_esc(chapter["summary"]), styles["Body"]))

    flow += _labeled_list("Covered topics", chapter.get("covered_topics"), styles)
    flow += _labeled_list("Learning objectives", chapter.get("learning_objectives"), styles)
    flow += _labeled_list("Key concepts", chapter.get("key_concepts"), styles, inline=True)
    flow += _labeled_list("Focus areas", chapter.get("focus_areas"), styles, inline=True)

    if plan:
        flow += _assessment_table(plan, styles)

    flow.append(Spacer(1, 12))
    return flow


def _assessment_table(plan: Dict[str, Any], styles) -> List[Any]:
    by_type = plan.get("by_type") or {}
    by_diff = plan.get("by_difficulty") or {}
    if not by_type and not by_diff:
        return []

    rows = [[Paragraph("<b>Assessment plan</b>", styles["Small"]),
             Paragraph("<b>Count</b>", styles["SmallRight"])]]
    for key, label in _TYPE_LABELS.items():
        if key in by_type:
            rows.append([Paragraph(_esc(label), styles["Small"]),
                         Paragraph(str(by_type[key]), styles["SmallRight"])])
    if by_diff:
        parts = [f"{_DIFFICULTY_LABELS.get(k, k)} {by_diff[k]}"
                 for k in ("easy", "medium", "hard") if k in by_diff]
        rows.append([Paragraph("<i>By difficulty</i>", styles["Small"]),
                     Paragraph(_esc(", ".join(parts)), styles["SmallRight"])])
    if plan.get("total_questions") is not None:
        rows.append([Paragraph("<b>Total</b>", styles["Small"]),
                     Paragraph(f"<b>{plan['total_questions']}</b>", styles["SmallRight"])])

    table = Table(rows, colWidths=[110 * mm, 30 * mm], hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _ACCENT),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _LIGHT]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#c9d2e0")),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    return [Spacer(1, 6), table]


# ------------------------------------------------------------------ #
# Helpers                                                            #
# ------------------------------------------------------------------ #
def _labeled_list(label, items, styles, *, inline: bool = False) -> List[Any]:
    if not items:
        return []
    flow: List[Any] = [Spacer(1, 6), Paragraph(f"<b>{_esc(label)}</b>", styles["Label"])]
    if inline:
        flow.append(Paragraph(_esc(", ".join(str(i) for i in items)), styles["Body"]))
    else:
        for item in items:
            flow.append(Paragraph("-&nbsp;&nbsp;" + _esc(str(item)), styles["BulletItem"]))
    return flow


def _pages(value) -> Optional[str]:
    if not value:
        return None
    return f"~{value} pages"


def _footer(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#8a93a5"))
    canvas.drawRightString(200 * mm, 12 * mm, f"Page {doc.page}")
    canvas.restoreState()


def _styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle("CoverTitle", parent=styles["Title"],
                              textColor=_ACCENT, fontSize=24, spaceAfter=2))
    styles.add(ParagraphStyle("Subtle", parent=styles["Normal"],
                              textColor=colors.HexColor("#6b7488"), fontSize=9))
    styles.add(ParagraphStyle("Chapter", parent=styles["Heading2"],
                              textColor=_ACCENT, spaceAfter=2))
    styles.add(ParagraphStyle("Label", parent=styles["Normal"],
                              textColor=colors.HexColor("#3a4560"), fontSize=9.5,
                              spaceAfter=1))
    styles.add(ParagraphStyle("Body", parent=styles["BodyText"], fontSize=10, leading=14))
    styles.add(ParagraphStyle("BulletItem", parent=styles["BodyText"], fontSize=10,
                              leading=14, leftIndent=12, spaceAfter=1))
    styles.add(ParagraphStyle("Small", parent=styles["Normal"], fontSize=9, leading=12))
    styles.add(ParagraphStyle("SmallRight", parent=styles["Normal"], fontSize=9,
                              leading=12, alignment=2))
    return styles


def _esc(value: str) -> str:
    """Escape XML-special characters for ReportLab Paragraph markup."""
    return (
        str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
