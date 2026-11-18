"""Run from orion_backend: python -m unittest src.modules.accessibility_word.tests.test_word_remediator"""
import hashlib
import io
import os
import tempfile
import unittest
from unittest import mock

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from src.modules.accessibility_word.engine.word_remediator.base_remediator import RemediationOptions
from src.modules.accessibility_word.engine.word_remediator.heading_remediator import HeadingRemediator
from src.modules.accessibility_word.engine.word_remediator.remediation_engine import (
    WordRemediationOrchestrator,
)
from src.modules.accessibility_word.engine.word_remediator.table_remediator import TableRemediator
from src.modules.accessibility_word.tests.test_word_validator import PNG, bad_doc, good_doc, save


def outcomes(report):
    return {r["rule_id"]: r["remediation_outcome"] for r in report["remediation_results"]}


def heading_levels(path):
    doc = Document(path)
    return [p.style.name for p in doc.paragraphs if p.style.name.startswith("Heading")]


class Base(unittest.TestCase):
    def run_remediation(self, doc, **kwargs):
        source = save(doc)
        target = source[:-5] + "_out.docx"
        self.addCleanup(lambda: [os.path.exists(p) and os.unlink(p) for p in (source, target)])
        options = kwargs.pop("options", None)
        report = WordRemediationOrchestrator(options=options).remediate(source, output_path=target, **kwargs)
        return source, target, report


class FixTests(Base):
    @staticmethod
    def digest(path):
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()

    def test_bad_document_is_improved_without_regressions(self):
        source, target, report = self.run_remediation(bad_doc(), document_name="upload.docx")
        self.assertEqual(report["status"], "completed")
        result = outcomes(report)
        for rule in ("MET-001", "MET-003", "STR-002", "STR-003", "STR-007"):
            self.assertEqual(result[rule], "fixed", rule)
        self.assertEqual(result["IMG-001"], "manual_review_required")
        self.assertEqual(report["summary"]["regressions"], 0)
        self.assertGreater(report["summary"]["score_after"], report["summary"]["score_before"])
        self.assertEqual(report["document_name"], "upload.docx")

    def test_input_file_is_never_modified(self):
        doc = bad_doc()
        source = save(doc)
        self.addCleanup(os.unlink, source)
        digest = self.digest(source)
        report = WordRemediationOrchestrator().remediate(source)
        self.addCleanup(os.unlink, report["remediated_path"])
        self.assertEqual(self.digest(source), digest)
        with self.assertRaises(ValueError):
            WordRemediationOrchestrator().remediate(source, output_path=source)

    def test_clean_document_is_left_alone(self):
        _, _, report = self.run_remediation(good_doc())
        self.assertEqual(report["summary"]["issues_before"], 0)
        self.assertTrue(all(r["remediator"] is None for r in report["remediation_results"]))
        self.assertEqual(report["summary"]["regressions"], 0)

    def test_hierarchy_keeps_structure(self):
        doc = good_doc()
        for level in (4, 5, 4):
            doc.add_heading(f"Level {level}", level=level)
        _, target, report = self.run_remediation(doc)
        self.assertEqual(outcomes(report)["STR-002"], "fixed")
        self.assertEqual(heading_levels(target), ["Heading 1", "Heading 2", "Heading 3", "Heading 4", "Heading 3"])

    def test_missing_heading_style_is_created(self):
        doc = good_doc()
        doc.add_heading("Deep", level=3)
        style = doc.styles["Heading 2"].element
        style.getparent().remove(style)
        for p in doc.paragraphs:
            ppr = p._p.pPr
            if ppr is not None and ppr.pStyle is not None and ppr.pStyle.val == "Heading2":
                ppr.remove(ppr.pStyle)
        _, target, report = self.run_remediation(doc)
        self.assertEqual(outcomes(report)["STR-002"], "fixed")
        self.assertIn("Heading 2", heading_levels(target))

    def test_header_row_is_inserted_in_schema_order(self):
        doc = good_doc()
        table = doc.add_table(rows=2, cols=1)
        table.cell(0, 0).text, table.cell(1, 0).text = "h", "v"
        trpr = table.rows[0]._tr.get_or_add_trPr()
        jc = OxmlElement("w:jc"); jc.set(qn("w:val"), "center"); trpr.append(jc)
        _, target, report = self.run_remediation(doc)
        self.assertEqual(outcomes(report)["TBL-001"], "fixed")
        tr = Document(target).tables[1].rows[0]._tr.trPr
        self.assertEqual([c.tag.split("}")[1] for c in tr], ["tblHeader", "jc"])

    def test_table_title_comes_from_caption(self):
        doc = good_doc()
        doc.add_paragraph("Table 2: Sales by region")
        table = doc.add_table(rows=2, cols=1)
        table.cell(0, 0).text, table.cell(1, 0).text = "h", "v"
        table.rows[0]._tr.get_or_add_trPr().append(OxmlElement("w:tblHeader"))
        _, target, report = self.run_remediation(doc)
        self.assertEqual(outcomes(report)["TBL-005"], "fixed")
        caption = Document(target).tables[1]._tbl.tblPr.find(qn("w:tblCaption"))
        self.assertEqual(caption.get(qn("w:val")), "Table 2: Sales by region")

    def test_title_from_file_name_is_flagged_for_review(self):
        _, _, report = self.run_remediation(bad_doc(), document_name="annual_report-2026.docx")
        action = next(r for r in report["remediation_results"] if r["rule_id"] == "MET-001")["actions"][0]
        self.assertIn("annual report 2026", action["action"])
        self.assertTrue(action["review_recommended"])

    def test_alt_text_provider(self):
        provider = mock.Mock(return_value="A bar chart of revenue")
        _, target, report = self.run_remediation(bad_doc(), options=RemediationOptions(alt_text_provider=provider))
        result = outcomes(report)
        self.assertEqual(result["IMG-001"], "fixed")
        self.assertEqual(result["IMG-002"], "fixed")
        self.assertEqual(provider.call_count, 2)
        self.assertTrue(isinstance(provider.call_args[0][0], bytes))


class IsolationTests(Base):
    def test_crashing_fix_is_rolled_back_and_others_still_apply(self):
        def half_then_crash(self, ctx, rec):
            for p in ctx.document.paragraphs:
                p.text = "CORRUPTED"
            raise RuntimeError("boom")

        with mock.patch.object(HeadingRemediator, "fix_hierarchy", half_then_crash):
            _, target, report = self.run_remediation(bad_doc())
        self.assertEqual(report["status"], "completed_with_errors")
        self.assertIn("boom", report["errors"][0])
        result = outcomes(report)
        self.assertEqual(result["STR-002"], "failed_to_fix")
        self.assertEqual(result["MET-001"], "fixed")
        self.assertEqual(result["STR-007"], "fixed")
        self.assertNotIn("CORRUPTED", [p.text for p in Document(target).paragraphs])

    def test_crashing_remediator_is_isolated(self):
        with mock.patch.object(TableRemediator, "remediate", side_effect=RuntimeError("table boom")):
            _, _, report = self.run_remediation(bad_doc())
        tables = next(r for r in report["remediator_results"] if r["remediator"] == "TableRemediator")
        self.assertEqual(tables["status"], "failed")
        self.assertEqual(outcomes(report)["TBL-001"], "failed_to_fix")
        self.assertEqual(outcomes(report)["MET-001"], "fixed")

    def test_invalid_upload_reports_failure(self):
        handle, path = tempfile.mkstemp(suffix=".docx")
        os.write(handle, b"not a docx")
        os.close(handle)
        self.addCleanup(os.unlink, path)
        report = WordRemediationOrchestrator().remediate(path)
        self.assertEqual(report["status"], "failed")
        self.assertIsNone(report["remediated_path"])
        self.assertTrue(report["errors"])


class ReportTests(Base):
    def test_report_fields_used_by_the_router(self):
        _, target, report = self.run_remediation(bad_doc())
        for key in ("status", "remediated_path", "errors", "summary", "issues_fixed",
                    "issues_failed", "remediation_results"):
            self.assertIn(key, report)
        for key in ("score_before", "score_after", "issues_fixed", "issues_failed", "issues_remaining"):
            self.assertIn(key, report["summary"])
        self.assertEqual(report["remediated_path"], target)
        self.assertEqual(len(report["remediation_results"]), 38)
        self.assertEqual(report["summary"]["issues_fixed"], len(report["issues_fixed"]))
        import json
        json.dumps(report)


if __name__ == "__main__":
    unittest.main()
