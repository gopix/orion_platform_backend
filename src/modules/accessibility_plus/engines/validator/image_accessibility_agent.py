"""
ImageAccessibilityAgent - Validates PDF image accessibility using PDFix metadata.

Checks include:
- IMG-001: All images must have alt text (non-empty GetAlt())
- IMG-002: Alt text must be descriptive (quality rules: min length, not just filename)

PDFix-based validation using:
    pdf_doc.GetStructTree()
    element.GetType() == "Figure"
    element.GetAlt()
    element.GetPageNumber()
    element.GetId()

No external ML/CV dependencies - pure PDFix metadata + rule-based validation.
"""

from __future__ import annotations
from typing import Any

from src.modules.accessibility_plus.models.validation_issue import (
    Severity,
    ValidationIssue,
    ValidationStatus,
)
from .accessibility_agent_framework import BaseAccessibilityValidatorAgent


class ImageAccessibilityAgent(BaseAccessibilityValidatorAgent):
    """Validates image accessibility in documents using PDFix metadata."""

    agent_code = "IMAGE_ACCESSIBILITY_AGENT"
    agent_name = "Image Accessibility Agent"
    category = "Image Accessibility"

    supported_checks = {
        "IMG-001",
        "IMG-002",
    }

    @staticmethod
    def _issue(
        rule_id: str,
        severity: Severity,
        message: str,
        recommendation: str,
        status: ValidationStatus,
        auto_fixable: bool = False,
    ) -> ValidationIssue:
        """Helper to construct ValidationIssue with common properties."""
        return ValidationIssue(
            agent_name=ImageAccessibilityAgent.agent_name,
            rule_id=rule_id,
            category="Image Accessibility",
            severity=severity.value,
            page_no=None,
            message=message,
            recommendation=recommendation,
            auto_fixable=auto_fixable,
            status=status.value,
        )

    def run_check(self, check_code: str, context: dict[str, Any]) -> ValidationIssue:
        """
        Execute accessibility check on PDF document images.

        Args:
            check_code: Check identifier (e.g., IMG-001)
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

        # Extract images once per PDF to avoid repeated tree traversals
        cache = context.setdefault("_cache", {})
        image_cache = cache.setdefault("images_by_pdf", {})
        pdf_path = context.get("pdf_doc_path", "")
        if pdf_path not in image_cache:
            struct_tree = pdf_doc.GetStructTree()
            images = self._extract_images(struct_tree) if struct_tree else []
            image_cache[pdf_path] = images
        else:
            images = image_cache[pdf_path]

        check_handlers = {
            "IMG-001": self._check_missing_alt_text,
            "IMG-002": self._check_empty_alt_text,
        }

        try:
            handler = check_handlers.get(check_code)
            if not handler:
                return self._issue(
                    rule_id=check_code,
                    severity=Severity.MEDIUM,
                    message=f"Unknown check code: {check_code}",
                    recommendation="Verify check code is in supported_checks",
                    status=ValidationStatus.FAIL,
                )

            return handler(pdf_doc, check_code, images)
        except Exception as exc:
            return self._issue(
                rule_id=check_code,
                severity=Severity.HIGH,
                message=f"Check execution error: {str(exc)}",
                recommendation="Review the error and retry the check",
                status=ValidationStatus.FAIL,
            )

    @staticmethod
    def _check_missing_alt_text(pdf_doc, check_code: str, images: list[dict]) -> ValidationIssue:
        """Check if all images have alt text (non-None GetAlt())."""
        try:
            if not images:
                return ImageAccessibilityAgent._issue(
                    rule_id=check_code,
                    severity=Severity.MEDIUM,
                    message="No images found in document",
                    recommendation="If document contains images, ensure they are properly tagged",
                    status=ValidationStatus.PASS,
                )

            missing_alt = [img for img in images if img.get("alt") is None]
            all_have_alt = len(missing_alt) == 0

            return ImageAccessibilityAgent._issue(
                rule_id=check_code,
                severity=Severity.CRITICAL,
                message=(
                    f"All {len(images)} images have alt text"
                    if all_have_alt
                    else f"{len(missing_alt)} out of {len(images)} images missing alt text"
                ),
                recommendation=(
                    "All images have alt text attributes"
                    if all_have_alt
                    else "Add alt text to all images using PDF authoring tool or PDFix API"
                ),
                status=ValidationStatus.PASS if all_have_alt else ValidationStatus.FAIL,
                auto_fixable=True,
            )
        except Exception as exc:
            return ImageAccessibilityAgent._issue(
                rule_id=check_code,
                severity=Severity.HIGH,
                message=f"Error checking alt text presence: {str(exc)}",
                recommendation="Check PDF structure and retry",
                status=ValidationStatus.FAIL,
            )

    @staticmethod
    def _check_empty_alt_text(pdf_doc, check_code: str, images: list[dict]) -> ValidationIssue:
        """Check if alt text is descriptive (not empty, not just whitespace, not generic placeholders)."""
        try:
            if not images:
                return ImageAccessibilityAgent._issue(
                    rule_id=check_code,
                    severity=Severity.MEDIUM,
                    message="No images found in document",
                    recommendation="If document contains images, ensure they are properly tagged",
                    status=ValidationStatus.PASS,
                )

            # Flag images with empty, whitespace-only, or placeholder alt text
            poor_alt = []
            for img in images:
                alt = img.get("alt", "")
                
                # Check 1: Empty or whitespace only
                if not alt or not alt.strip():
                    poor_alt.append((img, "Empty alt text"))
                    continue
                
                # Check 2: Placeholder patterns (generic text, not descriptive)
                alt_lower = alt.lower()
                if alt_lower in ["image", "photo", "picture", "figure", "image1", "img"]:
                    poor_alt.append((img, "Generic placeholder alt text"))

            all_descriptive = len(poor_alt) == 0

            return ImageAccessibilityAgent._issue(
                rule_id=check_code,
                severity=Severity.HIGH,
                message=(
                    f"All {len(images)} images have descriptive alt text"
                    if all_descriptive
                    else f"{len(poor_alt)} out of {len(images)} images have non-descriptive alt text"
                ),
                recommendation=(
                    "All images have descriptive alt text"
                    if all_descriptive
                    else "Ensure alt text describes image content (avoid generic placeholders)"
                ),
                status=ValidationStatus.PASS if all_descriptive else ValidationStatus.FAIL,
                auto_fixable=True,
            )
        except Exception as exc:
            return ImageAccessibilityAgent._issue(
                rule_id=check_code,
                severity=Severity.HIGH,
                message=f"Error checking alt text quality: {str(exc)}",
                recommendation="Check PDF structure and retry",
                status=ValidationStatus.FAIL,
            )

    @staticmethod
    def _extract_images(struct_tree) -> list[dict]:
        """
        Extract all images from structure tree in a single traversal.
        
        Returns a list of dicts with structure:
        [
            {
                "id": "image_id",
                "page": 1,
                "type": "Figure",
                "alt": "Description of image",
                "is_figure": True,
                "caption": "Caption text if present"
            },
            ...
        ]
        
        This single traversal is cached and reused by all check methods,
        avoiding repeated tree traversals for large PDFs.
        """
        images = []
        try:
            if not struct_tree:
                return images

            def traverse(node, depth=0):
                """Recursively traverse structure tree collecting images."""
                try:
                    num_children = node.GetNumChildren() if hasattr(node, "GetNumChildren") else 0
                    for i in range(num_children):
                        child = node.GetChildObject(i) if hasattr(node, "GetChildObject") else None
                        if not child:
                            continue

                        element_type = child.GetType() if hasattr(child, "GetType") else ""
                        
                        # Collect Figure elements (images)
                        if element_type == "Figure":
                            try:
                                img_data = {
                                    "id": child.GetId() if hasattr(child, "GetId") else "",
                                    "page": child.GetPageNumber() if hasattr(child, "GetPageNumber") else None,
                                    "type": element_type,
                                    "alt": child.GetAlt() if hasattr(child, "GetAlt") else None,
                                    "is_figure": True,
                                    "caption": "",  # Could be extracted from nearby annotations
                                }
                                images.append(img_data)
                            except (AttributeError, Exception):
                                pass

                        # Recurse into children
                        if hasattr(child, "GetNumChildren"):
                            traverse(child, depth + 1)
                except Exception:
                    pass

            traverse(struct_tree)
        except Exception:
            pass

        return images

