"""Run from orion_backend: python -m unittest src.modules.accessibility_word.tests.test_word_validator"""
import hashlib
import io
import os
import tempfile
import unittest
import zipfile
from unittest import mock

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Pt, RGBColor

from src.modules.accessibility_word.engine.word_validator.docx_parser import DocxParser
from src.modules.accessibility_word.engine.word_validator.visual_analyzer import (
    VisualAnalyzer,
    contrast_ratio,
)
from src.modules.accessibility_word.engine.word_validator.word_validation_orchestrator import (
    WordValidationOrchestrator,
)

PNG = bytes.fromhex(
    "89504E470D0A1A0A0000000D4948445200000001000000010804000000B51C0C02"
    "0000000B4944415478DA63FCFF1F0003030200EFBFA7DB0000000049454E44AE426082")


def set_language(doc, language="en-US"):
    defaults = doc.styles.element.find(qn("w:docDefaults"))
    rpr = defaults.find(qn("w:rPrDefault")).find(qn("w:rPr"))
    lang = rpr.find(qn("w:lang"))
    if lang is None:
        lang = OxmlElement("w:lang")
        rpr.append(lang)
    lang.set(qn("w:val"), language)


def good_doc():
    doc = Document()
    set_language(doc)
    doc.core_properties.title = "Annual report"
    doc.core_properties.author = "Orion"
    # The python-docx template's Heading 2 (#4F81BD at 13pt) really does fail 4.5:1.
    doc.styles["Heading 2"].font.color.rgb = RGBColor(0x1F, 0x3A, 0x5F)
    doc.add_heading("Introduction", level=1)
    doc.add_paragraph("A short opening paragraph.")
    doc.add_heading("Background", level=2)
    doc.add_paragraph("Item one", style="List Bullet")
    doc.add_picture(io.BytesIO(PNG))
    doc.inline_shapes[0]._inline.docPr.set("descr", "Revenue grew steadily over five years")
    table = doc.add_table(rows=2, cols=2)
    for row in table.rows:
        for cell in row.cells:
            cell.text = "value"
    header = OxmlElement("w:tblHeader")
    table.rows[0]._tr.get_or_add_trPr().append(header)
    caption = OxmlElement("w:tblCaption")
    caption.set(qn("w:val"), "Revenue table")
    table._tbl.tblPr.append(caption)
    return doc


def bad_doc():
    doc = Document()
    doc.core_properties.title = ""
    doc.core_properties.author = ""
    # python-docx's template carries a w:lang, so remove it to simulate an unset language.
    rpr = doc.styles.element.find(qn("w:docDefaults")).find(qn("w:rPrDefault")).find(qn("w:rPr"))
    for lang in rpr.findall(qn("w:lang")):
        rpr.remove(lang)
    doc.add_heading("Start", level=2)                 # STR-003
    doc.add_heading("Deep", level=4)                  # STR-002
    doc.add_paragraph("")
    doc.add_paragraph("")                             # STR-007
    doc.add_paragraph("• typed one")
    doc.add_paragraph("• typed two")                  # STR-006
    doc.add_picture(io.BytesIO(PNG))                  # IMG-001
    doc.add_picture(io.BytesIO(PNG))
    doc.inline_shapes[1]._inline.docPr.set("descr", "image1.png")  # IMG-002
    pale = doc.add_paragraph().add_run("Pale text")
    pale.font.color.rgb = RGBColor(0xDD, 0xDD, 0xDD)  # VIS-001
    tiny = doc.add_paragraph().add_run("Tiny text")
    tiny.font.size = Pt(6)                            # VIS-002
    doc.add_paragraph("Justified").alignment = WD_ALIGN_PARAGRAPH.JUSTIFY  # VIS-004
    table = doc.add_table(rows=2, cols=2)             # TBL-001, TBL-004, TBL-005
    table.cell(0, 0).merge(table.cell(0, 1))          # TBL-002
    return doc


def save(doc):
    handle, path = tempfile.mkstemp(suffix=".docx")
    os.close(handle)
    doc.save(path)
    return path


def rewrite_part(path, part, content):
    source = zipfile.ZipFile(path)
    items = {name: source.read(name) for name in source.namelist()}
    source.close()
    items[part] = content
    with zipfile.ZipFile(path, "w") as target:
        for name, data in items.items():
            target.writestr(name, data)


def statuses(report):
    return {
        check["rule_id"]: check["status"]
        for category in report["findings_by_category"].values()
        for check in category["checks"]
    }


class Base(unittest.TestCase):
    def path_for(self, doc):
        path = save(doc)
        self.addCleanup(os.unlink, path)
        return path


class DocumentContextTests(Base):
    def test_parsed_once_and_shared_by_all_analyzers(self):
        path = self.path_for(good_doc())
        orchestrator = WordValidationOrchestrator()
        seen = []
        for analyzer in orchestrator.analyzers:
            original = analyzer.analyze
            analyzer.analyze = (lambda fn: lambda ctx: (seen.append(ctx), fn(ctx))[1])(original)
        with mock.patch.object(DocxParser, "parse", autospec=True,
                               side_effect=DocxParser.parse) as parse:
            orchestrator.validate(path)
        self.assertEqual(parse.call_count, 1)
        self.assertEqual(len(seen), 7)
        self.assertTrue(all(ctx is seen[0] for ctx in seen))

    def test_analyzers_do_not_reopen_the_file(self):
        path = self.path_for(good_doc())
        orchestrator = WordValidationOrchestrator()
        context = orchestrator.docx_parser.parse(path)
        os.unlink(path)
        open(path, "wb").close()
        for analyzer in orchestrator.analyzers:
            self.assertEqual(analyzer.analyze(context).status, "completed")

    def test_alternate_content_is_not_counted_twice(self):
        doc = good_doc()
        paragraph = doc.add_paragraph()
        namespaces = nsdecls("w") + (
            ' xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"'
            ' xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"'
            ' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
            ' xmlns:v="urn:schemas-microsoft-com:vml"')
        run = parse_xml(f"""<w:r {namespaces}><mc:AlternateContent>
          <mc:Choice Requires="wps"><w:drawing><wp:inline><wp:docPr id="50" name="Box"/>
            <a:graphic><a:graphicData uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">
            <w:txbxContent><w:p><w:r><w:t>Boxed text</w:t></w:r></w:p></w:txbxContent>
            </a:graphicData></a:graphic></wp:inline></w:drawing></mc:Choice>
          <mc:Fallback><w:pict><v:shape id="s"><v:textbox><w:txbxContent>
            <w:p><w:r><w:t>Boxed text</w:t></w:r></w:p></w:txbxContent></v:textbox></v:shape></w:pict></mc:Fallback>
        </mc:AlternateContent></w:r>""")
        paragraph._p.append(run)
        context = DocxParser().parse(self.path_for(doc))
        self.assertEqual(len(context.text_boxes), 1)
        self.assertEqual(sum(p.text == "Boxed text" for p in context.paragraphs), 1)

    def test_missing_core_properties_are_not_invented(self):
        doc = good_doc()
        path = self.path_for(doc)
        source = zipfile.ZipFile(path)
        items = {n: source.read(n) for n in source.namelist() if n != "docProps/core.xml"}
        source.close()
        items["_rels/.rels"] = items["_rels/.rels"].replace(b"docProps/core.xml", b"docProps/none.xml")
        with zipfile.ZipFile(path, "w") as target:
            for name, data in items.items():
                target.writestr(name, data)
        report = WordValidationOrchestrator().validate(path)
        self.assertEqual(statuses(report)["MET-001"], "FAIL")


class DetectionTests(Base):
    def test_clean_document_has_no_failures(self):
        report = WordValidationOrchestrator().validate(self.path_for(good_doc()))
        self.assertEqual(report["summary"]["failed"], 0, report["remediation_recommendations"])
        self.assertEqual(report["accessibility_score"]["score"], 100.0)
        self.assertEqual(report["status"], "completed")

    def test_bad_document_is_flagged(self):
        result = statuses(WordValidationOrchestrator().validate(self.path_for(bad_doc())))
        for rule in ("STR-002", "STR-003", "STR-006", "STR-007", "IMG-001", "IMG-002", "MET-001",
                     "MET-002", "MET-003", "TBL-001", "TBL-002", "TBL-004", "TBL-005",
                     "VIS-001", "VIS-002", "VIS-004"):
            self.assertEqual(result[rule], "FAIL", rule)

    def test_heading_recommendation_names_the_right_level(self):
        report = WordValidationOrchestrator().validate(self.path_for(bad_doc()))
        finding = next(f for f in report["findings_by_category"]["STRUCTURAL_ACCESSIBILITY"]["findings"]
                       if f["rule_id"] == "STR-002")
        self.assertEqual(finding["severity"], "HIGH")
        self.assertEqual(finding["recommendation"], "Use Heading 3 instead of Heading 4")

    def test_contrast_ratio_reference_values(self):
        self.assertAlmostEqual(contrast_ratio("000000", "FFFFFF"), 21.0, places=2)
        self.assertAlmostEqual(contrast_ratio("777777", "FFFFFF"), 4.48, places=2)

    def test_white_text_on_cell_shading_is_not_flagged(self):
        doc = good_doc()
        cell = doc.tables[0].cell(0, 0)
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:fill"), "000000")
        cell._tc.get_or_add_tcPr().append(shd)
        run = cell.paragraphs[0].add_run(" white")
        run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        self.assertEqual(statuses(WordValidationOrchestrator().validate(self.path_for(doc)))["VIS-001"], "PASS")

    def test_color_inherited_from_style_is_resolved(self):
        doc = good_doc()
        doc.styles["Normal"].font.color.rgb = RGBColor(0xEE, 0xEE, 0xEE)
        doc.add_paragraph("Pale through inheritance")
        self.assertEqual(statuses(WordValidationOrchestrator().validate(self.path_for(doc)))["VIS-001"], "FAIL")

    def test_occurrence_cap_keeps_exact_count(self):
        doc = good_doc()
        for _ in range(150):
            run = doc.add_paragraph().add_run("Tiny")
            run.font.size = Pt(6)
        report = WordValidationOrchestrator().validate(self.path_for(doc))
        visual = report["findings_by_category"]["VISUAL_ACCESSIBILITY"]
        check = next(c for c in visual["checks"] if c["rule_id"] == "VIS-002")
        self.assertEqual(check["affected_count"], 150)
        self.assertEqual(sum(f["rule_id"] == "VIS-002" for f in visual["findings"]), 100)
        self.assertEqual(report["severity_distribution"]["MEDIUM"]["occurrences"], 150)


class ErrorIsolationTests(Base):
    def test_visual_crash_keeps_structure_results(self):
        path = self.path_for(bad_doc())
        with mock.patch.object(VisualAnalyzer, "analyze", side_effect=RuntimeError("boom")):
            report = WordValidationOrchestrator().validate(path)
        self.assertEqual(report["status"], "completed_with_errors")
        visual = report["findings_by_category"]["VISUAL_ACCESSIBILITY"]
        self.assertEqual(visual["status"], "failed")
        self.assertIn("boom", visual["errors"][0])
        self.assertEqual(visual["not_evaluated"], 5)
        structure = report["findings_by_category"]["STRUCTURAL_ACCESSIBILITY"]
        self.assertEqual(structure["status"], "completed")
        self.assertTrue(structure["findings"])
        self.assertEqual(report["accessibility_score"]["score_status"], "partial")
        self.assertLess(report["accessibility_score"]["coverage_percent"], 100)

    def test_one_crashing_check_only_loses_that_rule(self):
        path = self.path_for(bad_doc())
        with mock.patch.object(VisualAnalyzer, "check_vis_001_contrast", side_effect=KeyError("x")):
            report = WordValidationOrchestrator().validate(path)
        visual = report["findings_by_category"]["VISUAL_ACCESSIBILITY"]
        self.assertEqual(visual["status"], "partial")
        result = statuses(report)
        self.assertEqual(result["VIS-001"], "NOT_EVALUATED")
        self.assertEqual(result["VIS-002"], "FAIL")

    def test_failed_analyzers_do_not_change_the_passed_count(self):
        path = self.path_for(good_doc())
        with mock.patch.object(VisualAnalyzer, "analyze", side_effect=RuntimeError("boom")):
            report = WordValidationOrchestrator().validate(path)
        self.assertEqual(report["summary"]["not_evaluated"], 5)
        self.assertNotIn("PASS", {statuses(report)[f"VIS-00{i}"] for i in range(1, 6)})

    def test_corrupt_styles_fail_dependent_analyzers_only(self):
        path = self.path_for(bad_doc())
        rewrite_part(path, "word/styles.xml", b"<not-xml")
        report = WordValidationOrchestrator().validate(path)
        categories = report["findings_by_category"]
        self.assertEqual(categories["STRUCTURAL_ACCESSIBILITY"]["status"], "failed")
        self.assertEqual(categories["VISUAL_ACCESSIBILITY"]["status"], "failed")
        self.assertEqual(categories["TABLE_ACCESSIBILITY"]["status"], "completed")
        self.assertIn("styles", report["document"]["parse_warnings"])

    def test_unusable_uploads_raise_value_error(self):
        handle, path = tempfile.mkstemp(suffix=".docx")
        os.write(handle, b"this is not a zip")
        os.close(handle)
        self.addCleanup(os.unlink, path)
        with self.assertRaises(ValueError):
            WordValidationOrchestrator().validate(path)
        with zipfile.ZipFile(path, "w") as package:
            package.writestr("hello.txt", "no document here")
        with self.assertRaises(ValueError):
            WordValidationOrchestrator().validate(path)


class ScreenReaderTests(Base):
    def evidence(self, path, **overrides):
        with open(path, "rb") as fh:
            digest = hashlib.sha256(fh.read()).hexdigest()
        record = {"tool": "NVDA", "tool_version": "2026.1", "tester": "A. Tester",
                  "tested_at": "2026-11-03", "result": "PASS", "document_sha256": digest}
        record.update(overrides)
        return record

    def test_not_tested_by_default_and_excluded_from_score(self):
        report = WordValidationOrchestrator().validate(self.path_for(good_doc()))
        result = statuses(report)
        self.assertEqual(result["SRV-001"], "NOT_TESTED")
        self.assertEqual(result["SRV-002"], "NOT_TESTED")
        self.assertEqual(report["accessibility_score"]["score"], 100.0)
        self.assertFalse(report["accessibility_score"]["conformance_established"])
        pending = {item["rule_id"] for item in report["manual_validation_pending"]}
        self.assertTrue({"SRV-001", "SRV-002"} <= pending)

    def test_complete_evidence_is_accepted_per_tool(self):
        path = self.path_for(good_doc())
        report = WordValidationOrchestrator().validate(path, screen_reader_evidence=[self.evidence(path)])
        result = statuses(report)
        self.assertEqual(result["SRV-001"], "PASS")
        self.assertEqual(result["SRV-002"], "NOT_TESTED")

    def test_failed_evidence_is_a_failure(self):
        path = self.path_for(good_doc())
        report = WordValidationOrchestrator().validate(
            path, screen_reader_evidence=[self.evidence(path, result="FAIL", notes="Table not announced")])
        self.assertEqual(statuses(report)["SRV-001"], "FAIL")

    def test_incomplete_or_stale_evidence_is_rejected(self):
        path = self.path_for(good_doc())
        for bad in ({"tester": ""}, {"document_sha256": "0" * 64}, {"result": "LOOKS FINE"}):
            report = WordValidationOrchestrator().validate(
                path, screen_reader_evidence=[self.evidence(path, **bad)])
            self.assertEqual(statuses(report)["SRV-001"], "NOT_TESTED", bad)


class ReportTests(Base):
    KEYS = {"document", "accessibility_score", "summary", "findings_by_category",
            "severity_distribution", "manual_validation_pending", "remediation_recommendations"}

    def test_report_has_required_sections_and_consistent_totals(self):
        report = WordValidationOrchestrator().validate(self.path_for(bad_doc()), document_name="upload.docx")
        self.assertTrue(self.KEYS <= set(report))
        self.assertEqual(report["document_name"], "upload.docx")
        self.assertEqual(report["document"]["name"], "upload.docx")
        summary = report["summary"]
        self.assertEqual(summary["total_checks"],
                         summary["passed"] + summary["failed"] + summary["manual_validation_pending"])
        self.assertEqual(summary["total_checks"] + summary["not_applicable"] + summary["not_evaluated"], 38)
        categories = report["findings_by_category"].values()
        self.assertEqual(len(categories), 7)
        for field, key in (("passed", "passed"), ("failed", "failed"),
                           ("manual_pending", "manual_validation_pending"), ("total_checks", "total_checks")):
            self.assertEqual(sum(c[field] for c in categories), summary[key], field)
        self.assertEqual(sum(s["failed_checks"] for s in report["severity_distribution"].values()),
                         summary["failed"])
        self.assertEqual(len(report["remediation_recommendations"]), summary["failed"])
        self.assertEqual(len(report["manual_validation_pending"]), summary["manual_validation_pending"])

    def test_score_uses_severity_weights(self):
        report = WordValidationOrchestrator().validate(self.path_for(bad_doc()))
        weights = {"CRITICAL": 10, "HIGH": 5, "MEDIUM": 3, "LOW": 1}
        checks = [c for cat in report["findings_by_category"].values() for c in cat["checks"]]
        passed = sum(weights[c["severity"]] for c in checks if c["status"] == "PASS")
        failed = sum(weights[c["severity"]] for c in checks if c["status"] == "FAIL")
        self.assertEqual(report["accessibility_score"]["score"], round(100 * passed / (passed + failed), 1))

    def test_analyzer_result_matches_contract(self):
        report = WordValidationOrchestrator().validate(self.path_for(bad_doc()))
        structure = report["findings_by_category"]["STRUCTURAL_ACCESSIBILITY"]
        self.assertTrue({"analyzer", "category", "status", "total_checks", "passed", "failed",
                         "findings"} <= set(structure))
        self.assertEqual(structure["analyzer"], "StructureAnalyzer")
        self.assertTrue({"rule_id", "severity", "status", "issue", "location", "recommendation"}
                        <= set(structure["findings"][0]))

    def test_report_is_json_serializable(self):
        import json
        json.dumps(WordValidationOrchestrator().validate(self.path_for(bad_doc())))


if __name__ == "__main__":
    unittest.main()
