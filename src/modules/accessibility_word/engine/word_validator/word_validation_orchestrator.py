"""Runs the Word validation pipeline and returns one consolidated report."""
from __future__ import annotations

import logging
from typing import Any

from src.modules.accessibility_word.engine.word_validator.base_analyzer import BaseAnalyzer
from src.modules.accessibility_word.engine.word_validator.docx_parser import DocxParser
from src.modules.accessibility_word.engine.word_validator.image_analyzer import ImageAnalyzer
from src.modules.accessibility_word.engine.word_validator.metadata_analyzer import MetadataAnalyzer
from src.modules.accessibility_word.engine.word_validator.reading_order_analyzer import (
    ReadingOrderAnalyzer,
)
from src.modules.accessibility_word.engine.word_validator.rule_catalog import load_catalog
from src.modules.accessibility_word.engine.word_validator.rule_engine import (
    WordAccessibilityRuleEngine,
)
from src.modules.accessibility_word.engine.word_validator.scoring_engine import (
    WordAccessibilityScoringEngine,
)
from src.modules.accessibility_word.engine.word_validator.screen_reader_validator import (
    ScreenReaderValidator,
)
from src.modules.accessibility_word.engine.word_validator.structure_analyzer import (
    StructureAnalyzer,
)
from src.modules.accessibility_word.engine.word_validator.table_analyzer import TableAnalyzer
from src.modules.accessibility_word.engine.word_validator.visual_analyzer import VisualAnalyzer
from src.modules.accessibility_word.models.audit_models import AnalyzerResult
from src.modules.accessibility_word.models.finding_models import (
    AnalyzerStatus,
    CheckResult,
    CheckStatus,
)
from src.modules.accessibility_word.reporting.json_report import WordAccessibilityReportGenerator

logger = logging.getLogger(__name__)


class WordValidationOrchestrator:
    def __init__(self, analyzers: list[BaseAnalyzer] | None = None):
        self.catalog = load_catalog()
        self.docx_parser = DocxParser()
        self.analyzers = analyzers if analyzers is not None else [
            StructureAnalyzer(),
            ImageAnalyzer(),
            MetadataAnalyzer(),
            ReadingOrderAnalyzer(),
            TableAnalyzer(),
            VisualAnalyzer(),
            ScreenReaderValidator(),
        ]
        self.rule_engine = WordAccessibilityRuleEngine(self.catalog)
        self.scoring_engine = WordAccessibilityScoringEngine(self.catalog)
        self.report_generator = WordAccessibilityReportGenerator(self.catalog)

    def validate(
        self,
        file_path: str,
        organization_id: int | None = None,
        project_id: str | None = None,
        document_name: str | None = None,
        screen_reader_evidence: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Raises ValueError only when the file is not a usable DOCX."""
        # Parsed exactly once; every analyzer reads the same context.
        context = self.docx_parser.parse(file_path)
        if document_name:
            context.file_name = document_name
        context.screen_reader_evidence = list(screen_reader_evidence or [])

        results = [self._run_analyzer(analyzer, context) for analyzer in self.analyzers]
        evaluation = self.rule_engine.evaluate(results)
        scoring_result = self.scoring_engine.calculate(evaluation)
        report = self.report_generator.generate(context, evaluation, scoring_result)
        report["organization_id"] = organization_id
        report["project_id"] = project_id
        return report

    def _run_analyzer(self, analyzer: BaseAnalyzer, context) -> AnalyzerResult:
        """The last line of isolation: one analyzer can never lose another's results."""
        try:
            return analyzer.analyze(context)
        except Exception as exc:
            logger.exception("%s crashed", analyzer.name)
            return AnalyzerResult(
                analyzer=analyzer.name,
                category=analyzer.category,
                status=AnalyzerStatus.FAILED,
                errors=[f"{type(exc).__name__}: {exc}"],
                checks=[
                    CheckResult(rule.rule_id, rule.title, rule.severity,
                                CheckStatus.NOT_EVALUATED, detail="The analyzer crashed.")
                    for rule in self.catalog.for_analyzer(analyzer.name)
                ],
            )
