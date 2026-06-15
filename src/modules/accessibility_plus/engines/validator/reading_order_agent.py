"""
Reading Order Agent - Validates PDF reading order and structure.

Checks include:
- Untagged PDF: Detects if PDF lacks a structure tree
- Empty Structure Tree: Checks if structure tree exists but is empty
- Tag Order vs Content Order: Compares logical tag order with visual content order
- Multi-column Detection: Identifies multi-column layouts and validates reading order

Uses PDFix SDK for validation:
    pdf_doc.GetStructTree()
    page.AcquireWordList()
    page.GetContent()
    content.GetObject()
    object.GetBBox(), GetMcid(), GetText()
"""

from __future__ import annotations
from typing import Any
from src.modules.accessibility_plus.models.validation_issue import (
    Severity,
    ValidationIssue,
    ValidationStatus,
)
from .accessibility_agent_framework import BaseAccessibilityValidatorAgent


class ReadingOrderAgent(BaseAccessibilityValidatorAgent):
    """Validates PDF reading order and structure tree properties."""

    agent_code = "READING_ORDER_AGENT"
    agent_name = "Reading Order Agent"
    category = "Document Structure"
    LINE_Y_TOLERANCE = 5.0

    supported_checks = {
        "UNTAGGED_PDF",
        "EMPTY_STRUCTURE_TREE",
        "CONTENT_EXTRACTION_VALIDATION",
        "MULTICOLUMN_POSSIBLE",
        "WORD_READING_ORDER",
    }

    @staticmethod
    def _issue(
        rule_id: str,
        severity: Severity,
        message: str,
        recommendation: str,
        status: ValidationStatus,
        page_no: int | None = None,
        auto_fixable: bool = False,
        internal_check: bool = False,
    ) -> ValidationIssue:
        return ValidationIssue(
            agent_name=ReadingOrderAgent.agent_name,
            rule_id=rule_id,
            category="Document Structure",
            severity=severity.value,
            page_no=page_no,
            message=message,
            recommendation=recommendation,
            auto_fixable=auto_fixable,
            status=status.value,
            internal_check=internal_check,
        )

    @staticmethod
    def _safe_call(obj: Any, method_name: str, *args: Any) -> tuple[bool, Any]:
        """
        Safely call a method on an object, handling missing methods and exceptions.

        Args:
            obj: Object to call method on
            method_name: Name of method to call
            *args: Arguments to pass to method

        Returns:
            Tuple of (success: bool, result: Any)
        """
        if obj is None or not hasattr(obj, method_name):
            return False, None
        try:
            result = getattr(obj, method_name)(*args)
            return True, result
        except Exception:
            return False, None

    @staticmethod
    def _parse_bbox_to_dict(bbox: Any) -> dict | None:
        """Parse bounding box object to structured dict with left, top, right, bottom."""
        if bbox is None:
            return None

        try:
            # Try attribute-based access (standard PDFix bbox format)
            for fields in (("left", "top", "right", "bottom"), ("x1", "y1", "x2", "y2")):
                if all(hasattr(bbox, f) for f in fields):
                    if fields == ("x1", "y1", "x2", "y2"):
                        return {
                            "left": float(getattr(bbox, "x1")),
                            "top": float(getattr(bbox, "y1")),
                            "right": float(getattr(bbox, "x2")),
                            "bottom": float(getattr(bbox, "y2")),
                        }
                    else:
                        return {
                            "left": float(getattr(bbox, "left")),
                            "top": float(getattr(bbox, "top")),
                            "right": float(getattr(bbox, "right")),
                            "bottom": float(getattr(bbox, "bottom")),
                        }
        except (ValueError, AttributeError, TypeError):
            pass

        return None

    def _get_document_mode(self, pdf_doc: Any) -> dict[str, Any]:
        """
        Determine reading-order analysis mode based on tagging availability.

        Returns:
            {
                "mode": "TAGGED" | "UNTAGGED",
                "has_struct_tree": bool,
            }
        """
        ok_tree, struct_tree = self._safe_call(pdf_doc, "GetStructTree")
        has_struct_tree = bool(ok_tree and struct_tree is not None)

        return {
            "mode": "TAGGED" if has_struct_tree else "UNTAGGED",
            "has_struct_tree": has_struct_tree,
        }

    def _check_untagged_pdf(
        self,
        pdf_doc: Any,
        document_mode: dict[str, Any] | None = None,
    ) -> ValidationIssue:
        """Check 1: Detect if PDF is untagged (no structure tree)."""
        mode_info = document_mode or self._get_document_mode(pdf_doc)
        is_untagged = mode_info.get("mode") == "UNTAGGED"

        if is_untagged:
            return self._issue(
                rule_id="UNTAGGED_PDF",
                severity=Severity.CRITICAL,
                message="PDF document is untagged - no structure tree present",
                recommendation="Add structure tree and logical tags to the PDF document for accessibility",
                status=ValidationStatus.FAIL,
            )

        return self._issue(
            rule_id="UNTAGGED_PDF",
            severity=Severity.LOW,
            message="PDF document has structure tree",
            recommendation="",
            status=ValidationStatus.PASS,
        )

    def _check_empty_structure_tree(
        self,
        pdf_doc: Any,
        document_mode: dict[str, Any] | None = None,
    ) -> ValidationIssue:
        """Check 2: Detect if structure tree is empty."""
        mode_info = document_mode or self._get_document_mode(pdf_doc)
        if mode_info.get("mode") == "UNTAGGED":
            return self._issue(
                rule_id="EMPTY_STRUCTURE_TREE",
                severity=Severity.LOW,
                message="Skipped: EMPTY_STRUCTURE_TREE is not applicable when mode=UNTAGGED",
                recommendation="Use UNTAGGED_PDF as the primary finding for this document",
                status=ValidationStatus.INFO,
                internal_check=True,
            )

        ok_tree, struct_tree = self._safe_call(pdf_doc, "GetStructTree")

        if not ok_tree or struct_tree is None:
            return self._issue(
                rule_id="EMPTY_STRUCTURE_TREE",
                severity=Severity.CRITICAL,
                message="PDF has no structure tree",
                recommendation="Create a structure tree for the document",
                status=ValidationStatus.FAIL,
            )

        # Try multiple methods to get root item - PDFix API may vary
        root = None

        # Method 1: Try GetRootItem() (standard method)
        ok_root, root_item = self._safe_call(struct_tree, "GetRootItem")
        if ok_root and root_item is not None:
            root = root_item

        # Method 2: If GetRootItem not available, try GetRoot()
        if root is None:
            ok_root, root_item = self._safe_call(struct_tree, "GetRoot")
            if ok_root and root_item is not None:
                root = root_item

        # Method 3: If neither works, try to access first child directly
        if root is None:
            ok_children, num_children = self._safe_call(struct_tree, "GetNumChildren")
            if ok_children and isinstance(num_children, int) and num_children > 0:
                # Structure tree has children, so it's not empty
                return self._issue(
                    rule_id="EMPTY_STRUCTURE_TREE",
                    severity=Severity.LOW,
                    message=f"Structure tree present with {num_children} root children",
                    recommendation="",
                    status=ValidationStatus.PASS,
                )
            else:
                # Could not determine root and no children found
                return self._issue(
                    rule_id="EMPTY_STRUCTURE_TREE",
                    severity=Severity.CRITICAL,
                    message="Structure tree root is inaccessible (GetRootItem/GetRoot/GetNumChildren all failed)",
                    recommendation="Verify PDF is properly tagged. Check PDFix SDK documentation for structure tree access methods.",
                    status=ValidationStatus.FAIL,
                )

        # If we got a root item, check if it has children
        ok_children, num_children = self._safe_call(root, "GetNumChildren")
        if not ok_children or num_children == 0:
            return self._issue(
                rule_id="EMPTY_STRUCTURE_TREE",
                severity=Severity.CRITICAL,
                message="Structure tree root has no children - document structure is empty",
                recommendation="Tag document content and add children to the structure tree root",
                status=ValidationStatus.FAIL,
            )

        return self._issue(
            rule_id="EMPTY_STRUCTURE_TREE",
            severity=Severity.LOW,
            message=f"Structure tree present with {num_children} root children",
            recommendation="",
            status=ValidationStatus.PASS,
        )

    def _extract_page_objects(self, pdf_doc: Any, page_index: int) -> list[dict]:
        """Extract page objects with text, MCID, and bounding box."""
        page_objects = []

        ok_page, page = self._safe_call(pdf_doc, "AcquirePage", page_index)
        if not ok_page or not page:
            return page_objects

        try:
            ok_content, content = self._safe_call(page, "GetContent")
            if not ok_content or not content:
                return page_objects

            ok_count, obj_count = self._safe_call(content, "GetNumObjects")
            if not ok_count or not isinstance(obj_count, int):
                return page_objects

            for obj_index in range(obj_count):
                ok_obj, obj = self._safe_call(content, "GetObject", obj_index)
                if not ok_obj or not obj:
                    continue

                ok_text, text_val = self._safe_call(obj, "GetText")
                text = str(text_val).strip() if ok_text and text_val else ""

                ok_mcid, mcid_val = self._safe_call(obj, "GetMcid")
                mcid = mcid_val if ok_mcid else None

                ok_bbox, bbox_val = self._safe_call(obj, "GetBBox")
                bbox = self._parse_bbox_to_dict(bbox_val) if ok_bbox else None

                page_objects.append(
                    {
                        "index": obj_index,
                        "text": text,
                        "mcid": mcid,
                        "bbox": bbox,
                    }
                )
        finally:
            self._safe_call(page, "Release")

        return page_objects

    def _extract_word_list(
        self,
        pdf_doc: Any,
        page_index: int,
        alg: int = -1,
        flags: int = 0,
    ) -> list[dict]:
        """Extract word list from page with position information."""
        words = []

        ok_page, page = self._safe_call(pdf_doc, "AcquirePage", page_index)
        if not ok_page or not page:
            return words

        try:
            ok_word_list, word_list = self._safe_call(page, "AcquireWordList", alg, flags)
            if not ok_word_list or not word_list:
                return words

            ok_count, num_words = self._safe_call(word_list, "GetNumWords")
            if not ok_count or not isinstance(num_words, int):
                self._safe_call(word_list, "Release")
                return words

            for i in range(num_words):
                ok_word, word = self._safe_call(word_list, "GetWord", i)
                if not ok_word or not word:
                    continue

                ok_text, text_val = self._safe_call(word, "GetText")
                text = str(text_val).strip() if ok_text and text_val else ""

                ok_bbox, bbox_val = self._safe_call(word, "GetBBox")
                bbox = self._parse_bbox_to_dict(bbox_val) if ok_bbox else None

                words.append(
                    {
                        "index": i,
                        "text": text,
                        "bbox": bbox,
                    }
                )

            self._safe_call(word_list, "Release")
        finally:
            self._safe_call(page, "Release")

        return words

    def _detect_multicolumn_layout(self, words: list[dict]) -> dict[str, Any]:
        """
        Detect potential multi-column layout using histogram bucketing on X coordinates.
        
        Args:
            words: List of word dicts with bbox info (bbox is a dict with left, top, right, bottom)
        
        Returns:
            dict with detected_columns (int), layout_info (str), and is_multicolumn (bool)
        """
        if not words or len(words) < 5:
            return {
                "detected_columns": 1,
                "layout_info": "Insufficient words for layout analysis",
                "is_multicolumn": False,
            }

        # Extract X coordinates from bounding boxes
        x_positions = []
        for word in words:
            bbox = word.get("bbox")
            if not bbox or not isinstance(bbox, dict):
                continue

            x_left = bbox.get("left")
            if x_left is not None:
                x_positions.append(float(x_left))

        if len(x_positions) < 5:
            return {
                "detected_columns": 1,
                "layout_info": f"Could not extract positions from {len(words)} words",
                "is_multicolumn": False,
            }

        # Histogram bucketing: divide X-axis into buckets to detect clusters
        # This handles centered text, different alignments better than gap-based approach
        min_x = min(x_positions)
        max_x = max(x_positions)
        x_range = max_x - min_x

        if x_range < 50:  # Document too narrow for multi-column
            return {
                "detected_columns": 1,
                "layout_info": f"X-range too small: {x_range:.2f} points",
                "is_multicolumn": False,
            }

        # Use 10 buckets for histogram
        num_buckets = 10
        bucket_size = x_range / num_buckets
        buckets = [0] * num_buckets

        for x in x_positions:
            bucket_idx = min(int((x - min_x) / bucket_size), num_buckets - 1)
            buckets[bucket_idx] += 1

        # Find significant clusters (buckets with meaningful word density)
        total_words = len(x_positions)
        threshold = total_words / 10  # At least 10% of words in a bucket
        significant_buckets = [i for i, count in enumerate(buckets) if count >= threshold]

        if not significant_buckets:
            return {
                "detected_columns": 1,
                "layout_info": "No significant word clusters detected",
                "is_multicolumn": False,
            }

        # Count clusters (consecutive significant buckets form one cluster)
        clusters = []
        current_cluster_start = significant_buckets[0]
        for i in range(1, len(significant_buckets)):
            if significant_buckets[i] - significant_buckets[i - 1] > 1:
                # Gap found, end current cluster
                clusters.append((current_cluster_start, significant_buckets[i - 1]))
                current_cluster_start = significant_buckets[i]
        clusters.append((current_cluster_start, significant_buckets[-1]))

        # Convert bucket clusters into word-density clusters and keep only substantial ones.
        # This avoids over-detection from small sidebars/captions/list fragments.
        min_words_per_column = max(3, int(total_words * 0.20))
        substantial_cluster_word_counts = []
        for start_idx, end_idx in clusters:
            cluster_word_count = sum(buckets[idx] for idx in range(start_idx, end_idx + 1))
            if cluster_word_count >= min_words_per_column:
                substantial_cluster_word_counts.append(cluster_word_count)

        num_detected_columns = len(substantial_cluster_word_counts)
        is_multicolumn = num_detected_columns >= 2

        if not is_multicolumn:
            num_detected_columns = 1

        layout_info = (
            f"Histogram analysis: {num_detected_columns} substantial cluster(s) detected. "
            f"Analyzed {len(x_positions)} words across {x_range:.2f} point width. "
            f"Min words/column threshold={min_words_per_column}."
        )

        return {
            "detected_columns": num_detected_columns,
            "layout_info": layout_info,
            "is_multicolumn": is_multicolumn,
            "clusters": clusters,
        }

    def _check_content_extraction_validation(self, pdf_doc: Any) -> ValidationIssue:
        """Check 3: Validate that page content and words can be extracted from PDF."""
        ok_num_pages, num_pages = self._safe_call(pdf_doc, "GetNumPages")
        if not ok_num_pages or not isinstance(num_pages, int) or num_pages == 0:
            return self._issue(
                rule_id="CONTENT_EXTRACTION_VALIDATION",
                severity=Severity.MEDIUM,
                message="Could not access document pages",
                recommendation="Ensure PDF is valid and contains pages",
                status=ValidationStatus.FAIL,
                internal_check=True,
            )

        # Analyze first page only for efficiency
        page_index = 0

        # Extract objects from content stream
        page_objects = self._extract_page_objects(pdf_doc, page_index)
        if not page_objects:
            return self._issue(
                rule_id="CONTENT_EXTRACTION_VALIDATION",
                severity=Severity.MEDIUM,
                message="Could not extract page objects from content stream",
                recommendation="Ensure page has content objects in the PDF",
                status=ValidationStatus.FAIL,
                internal_check=True,
            )

        # Extract words using PDFix word list API
        words = self._extract_word_list(pdf_doc, page_index)
        if not words:
            return self._issue(
                rule_id="CONTENT_EXTRACTION_VALIDATION",
                severity=Severity.MEDIUM,
                message="Could not extract word list from page",
                recommendation="Ensure page has text content that can be extracted",
                status=ValidationStatus.FAIL,
                internal_check=True,
            )

        # Analyze extracted content
        multicolumn_info = self._detect_multicolumn_layout(words)

        # Build status message
        status_msg = (
            f"Successfully extracted page {page_index}: {len(page_objects)} objects, {len(words)} words. "
            f"Layout analysis: {multicolumn_info['detected_columns']} column(s). "
        )

        # Only report failures if content extraction genuinely failed
        if multicolumn_info["is_multicolumn"]:
            return self._issue(
                rule_id="CONTENT_EXTRACTION_VALIDATION",
                severity=Severity.LOW,
                message=status_msg + "Note: Multi-column layout detected.",
                recommendation="For multi-column PDFs, verify reading order separately using dedicated tag order analysis.",
                status=ValidationStatus.PASS,
                internal_check=True,
            )

        return self._issue(
            rule_id="CONTENT_EXTRACTION_VALIDATION",
            severity=Severity.LOW,
            message=status_msg + "Content extraction successful.",
            recommendation="",
            status=ValidationStatus.PASS,
            internal_check=True,
        )

    def _check_multicolumn_possible(self, pdf_doc: Any) -> ValidationIssue:
        """Check 4: Detect potential multi-column layout using histogram clustering."""
        ok_num_pages, num_pages = self._safe_call(pdf_doc, "GetNumPages")
        if not ok_num_pages or not isinstance(num_pages, int) or num_pages == 0:
            return self._issue(
                rule_id="MULTICOLUMN_POSSIBLE",
                severity=Severity.LOW,
                message="Could not access document pages",
                recommendation="",
                status=ValidationStatus.FAIL,
            )

        # Analyze first 5 pages for multi-column patterns
        multicolumn_candidates = []
        for page_index in range(min(num_pages, 5)):
            words = self._extract_word_list(pdf_doc, page_index)
            if words:
                layout_info = self._detect_multicolumn_layout(words)
                if layout_info["is_multicolumn"]:
                    multicolumn_candidates.append(
                        {
                            "page": page_index,
                            "columns": layout_info["detected_columns"],
                        }
                    )

        if multicolumn_candidates:
            page_list = ", ".join(
                f"pg{p['page']}({p['columns']}col)" for p in multicolumn_candidates[:3]
            )
            return self._issue(
                rule_id="MULTICOLUMN_POSSIBLE",
                severity=Severity.MEDIUM,
                message=f"Multi-column layout possible on pages: {page_list}",
                recommendation="Manually verify layout. If multi-column, ensure reading order follows correct sequence (top-to-bottom within each column, left-to-right across columns).",
                status=ValidationStatus.WARNING,
            )

        return self._issue(
            rule_id="MULTICOLUMN_POSSIBLE",
            severity=Severity.LOW,
            message="Single-column layout detected in sampled pages",
            recommendation="",
            status=ValidationStatus.PASS,
        )

    def _reconstruct_lines_from_words(
        self,
        words: list[dict],
        y_tolerance: float | None = None,
    ) -> list[list[dict]]:
        """
        Reconstruct lines by grouping consecutive words with similar Y coordinates.
        
        Args:
            words: List of word dicts with bbox info (bbox is a dict with left, top, right, bottom)
            y_tolerance: Vertical distance threshold to group words on same line
            
        Returns:
            List of lines, where each line is a list of words
        """
        if not words:
            return []

        if y_tolerance is None or y_tolerance <= 0:
            y_tolerance = self.LINE_Y_TOLERANCE

        # Extract Y positions from words
        lines = []
        current_line = []
        current_y = None

        for word in words:
            bbox = word.get("bbox")
            if not bbox or not isinstance(bbox, dict):
                continue

            y_pos = bbox.get("top")
            if y_pos is None:
                continue

            # Start new line if Y coordinate changed significantly
            if current_y is None or abs(y_pos - current_y) > y_tolerance:
                if current_line:
                    lines.append(current_line)
                current_line = [word]
                current_y = y_pos
            else:
                current_line.append(word)

        # Add last line
        if current_line:
            lines.append(current_line)

        return lines

    def _get_line_y_position(self, line: list[dict]) -> float:
        """Extract Y position (top coordinate) from first word in a line."""
        if not line:
            return 0.0

        bbox = line[0].get("bbox")
        if not bbox or not isinstance(bbox, dict):
            return 0.0

        y_pos = bbox.get("top")
        return float(y_pos) if y_pos is not None else 0.0

    def _check_word_reading_order(
        self,
        pdf_doc: Any,
        line_y_tolerance: float | None = None,
    ) -> ValidationIssue:
        """Check 5: Validate line reading order using PDFix word list API."""
        ok_num_pages, num_pages = self._safe_call(pdf_doc, "GetNumPages")
        if not ok_num_pages or not isinstance(num_pages, int) or num_pages == 0:
            return self._issue(
                rule_id="WORD_READING_ORDER",
                severity=Severity.LOW,
                message="Could not access document pages",
                recommendation="",
                status=ValidationStatus.FAIL,
            )

        # Analyze first page
        page_index = 0
        words = self._extract_word_list(pdf_doc, page_index)

        if not words:
            return self._issue(
                rule_id="WORD_READING_ORDER",
                severity=Severity.MEDIUM,
                message=f"Could not extract word list from page {page_index}",
                recommendation="Ensure page has text content with proper encoding",
                status=ValidationStatus.FAIL,
            )

        # Check for multi-column layout first
        multicolumn_info = self._detect_multicolumn_layout(words)
        if multicolumn_info["is_multicolumn"]:
            # Skip line order validation for multi-column layouts
            # They have complex reading orders that require separate analysis
            return self._issue(
                rule_id="WORD_READING_ORDER",
                severity=Severity.LOW,
                message=f"Multi-column layout detected ({multicolumn_info['detected_columns']} columns) - line order check skipped. Use dedicated multi-column reading order tools.",
                recommendation="For multi-column PDFs, manually verify reading order or use specialized analysis.",
                status=ValidationStatus.PASS,
            )

        # Reconstruct lines from words (group by Y position)
        lines = self._reconstruct_lines_from_words(words, y_tolerance=line_y_tolerance)

        if len(lines) < 2:
            return self._issue(
                rule_id="WORD_READING_ORDER",
                severity=Severity.LOW,
                message=f"Extracted {len(words)} words forming {len(lines)} line(s)",
                recommendation="",
                status=ValidationStatus.PASS,
            )

        # Check if line Y positions are properly ordered (decreasing in PDF coords)
        line_y_positions = [self._get_line_y_position(line) for line in lines]

        # Verify lines are in correct order (Y should be decreasing: top-to-bottom)
        is_ordered = all(
            line_y_positions[i] >= line_y_positions[i + 1]
            for i in range(len(line_y_positions) - 1)
        )

        if is_ordered:
            return self._issue(
                rule_id="WORD_READING_ORDER",
                severity=Severity.LOW,
                message=f"Line reading order appears correct ({len(lines)} lines, {len(words)} words on page {page_index})",
                recommendation="",
                status=ValidationStatus.PASS,
            )
        else:
            # Find first disorder (where Y increased instead of staying same or decreasing)
            disorder_at_line = 0
            for i in range(len(line_y_positions) - 1):
                if line_y_positions[i] < line_y_positions[i + 1]:
                    disorder_at_line = i
                    break

            y_current = line_y_positions[disorder_at_line]
            y_next = line_y_positions[disorder_at_line + 1]

            return self._issue(
                rule_id="WORD_READING_ORDER",
                severity=Severity.MEDIUM,
                message=(
                    f"Possible line reading order anomaly: line {disorder_at_line} "
                    f"(Y={y_current:.1f}) appears before line {disorder_at_line + 1} "
                    f"(Y={y_next:.1f}). This is a visual inference and may be caused by layout quirks."
                ),
                recommendation=(
                    "Manually verify reading order for this page. "
                    "Treat this as a heuristic signal, not a definitive failure."
                ),
                status=ValidationStatus.WARNING,
            )

    def run_check(self, check_code: str, context: dict[str, Any]) -> ValidationIssue:
        """
        Execute reading order check on PDF document.

        Args:
            check_code: Check identifier (e.g., UNTAGGED_PDF, EMPTY_STRUCTURE_TREE)
            context: Context dict containing:
                - pdf_doc: PDFix PdfDoc object (opened and ready)
                - pdf_doc_path: Path to PDF file
                - organization_id: Organization context
                - project_id: Project context

        Returns:
            ValidationIssue with check results
        """
        if check_code not in self.supported_checks:
            return self._issue(
                rule_id=check_code,
                severity=Severity.MEDIUM,
                message=f"Check code {check_code} is not supported",
                recommendation="Use a valid check code from supported_checks",
                status=ValidationStatus.FAIL,
            )

        pdf_doc = context.get("pdf_doc")
        if not pdf_doc:
            return self._issue(
                rule_id=check_code,
                severity=Severity.CRITICAL,
                message="PDF document not provided in context",
                recommendation="Ensure PDF document is opened and provided in context",
                status=ValidationStatus.FAIL,
            )

        raw_line_y_tolerance = context.get("line_y_tolerance", self.LINE_Y_TOLERANCE)
        try:
            line_y_tolerance = float(raw_line_y_tolerance)
        except (TypeError, ValueError):
            line_y_tolerance = self.LINE_Y_TOLERANCE

        document_mode = self._get_document_mode(pdf_doc)
        context.setdefault("_cache", {})
        context["_cache"]["reading_order_document_mode"] = document_mode

        # Route to appropriate check method
        check_methods = {
            "CONTENT_EXTRACTION_VALIDATION": self._check_content_extraction_validation,
            "MULTICOLUMN_POSSIBLE": self._check_multicolumn_possible,
        }

        if check_code == "UNTAGGED_PDF":
            return self._check_untagged_pdf(
                pdf_doc,
                document_mode=document_mode,
            )

        if check_code == "EMPTY_STRUCTURE_TREE":
            return self._check_empty_structure_tree(
                pdf_doc,
                document_mode=document_mode,
            )

        if check_code == "WORD_READING_ORDER":
            return self._check_word_reading_order(
                pdf_doc,
                line_y_tolerance=line_y_tolerance,
            )

        check_method = check_methods.get(check_code)
        if check_method:
            return check_method(pdf_doc)

        return self._issue(
            rule_id=check_code,
            severity=Severity.MEDIUM,
            message=f"Check method not implemented for {check_code}",
            recommendation="",
            status=ValidationStatus.FAIL,
        )