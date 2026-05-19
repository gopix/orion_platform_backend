from __future__ import annotations

from typing import Any

from src.modules.accessibility_plus.engines.accessibility_agent_framework import BaseAccessibilityAgent


class ImageAccessibilityAgent(BaseAccessibilityAgent):
	agent_code = "IMAGE_ACCESSIBILITY_AGENT"

	ALT_TEXT_MISSING = "ALT_TEXT_MISSING"
	EMPTY_ALT_TEXT = "EMPTY_ALT_TEXT"
	DECORATIVE_IMAGE_MISSING_MARKER = "DECORATIVE_IMAGE_MISSING_MARKER"
	IMAGE_WITHOUT_TAG = "IMAGE_WITHOUT_TAG"
	LOW_QUALITY_ALT_TEXT = "LOW_QUALITY_ALT_TEXT"

	supported_checks = {
		ALT_TEXT_MISSING,
		EMPTY_ALT_TEXT,
		DECORATIVE_IMAGE_MISSING_MARKER,
		IMAGE_WITHOUT_TAG,
		LOW_QUALITY_ALT_TEXT,
	}

	_LOW_QUALITY_ALT_TERMS = {"image", "photo", "pic", "picture", "figure", "graphic"}

	def run_check(self, check_code: str, context: dict[str, Any]) -> dict[str, Any]:
		images = self._extract_images(context)

		if check_code == self.ALT_TEXT_MISSING:
			findings = self._check_alt_text_missing(images)
		elif check_code == self.EMPTY_ALT_TEXT:
			findings = self._check_empty_alt_text(images)
		elif check_code == self.DECORATIVE_IMAGE_MISSING_MARKER:
			findings = self._check_decorative_image_missing_marker(images)
		elif check_code == self.IMAGE_WITHOUT_TAG:
			findings = self._check_image_without_tag(images)
		elif check_code == self.LOW_QUALITY_ALT_TEXT:
			findings = self._check_low_quality_alt_text(images)
		else:
			return {
				"check_code": check_code,
				"passed": False,
				"message": f"{check_code} is not implemented for {self.agent_code}",
				"value": [],
			}

		passed = len(findings) == 0
		return {
			"check_code": check_code,
			"passed": passed,
			"message": "No issues found" if passed else f"{len(findings)} issue(s) found",
			"value": findings,
		}

	def _extract_images(self, context: dict[str, Any]) -> list[dict[str, Any]]:
		raw_images = context.get("images")
		if isinstance(raw_images, list):
			return [item for item in raw_images if isinstance(item, dict)]

		raw_figures = context.get("figures")
		if isinstance(raw_figures, list):
			return [item for item in raw_figures if isinstance(item, dict)]

		return []

	def _check_alt_text_missing(self, images: list[dict[str, Any]]) -> list[dict[str, Any]]:
		findings: list[dict[str, Any]] = []
		for image in images:
			if self._is_decorative(image):
				continue

			if "alt_text" not in image:
				findings.append(
					self._build_finding(
						check_code=self.ALT_TEXT_MISSING,
						image=image,
						severity="HIGH",
						description="Image missing alternative text",
						recommendation="Add meaningful alt text",
					)
				)
		return findings

	def _check_empty_alt_text(self, images: list[dict[str, Any]]) -> list[dict[str, Any]]:
		findings: list[dict[str, Any]] = []
		for image in images:
			if self._is_decorative(image):
				continue

			alt_text = image.get("alt_text")
			if alt_text is None:
				continue

			if str(alt_text).strip() == "":
				findings.append(
					self._build_finding(
						check_code=self.EMPTY_ALT_TEXT,
						image=image,
						severity="HIGH",
						description="Meaningful image has empty alt text",
						recommendation="Provide a concise, meaningful alt text",
					)
				)
		return findings

	def _check_decorative_image_missing_marker(self, images: list[dict[str, Any]]) -> list[dict[str, Any]]:
		findings: list[dict[str, Any]] = []
		for image in images:
			decorative_hint = image.get("decorative")
			marker_present = image.get("decorative_marker")

			# If image indicates decorative intent but marker is absent/false.
			if decorative_hint is True and marker_present is not True:
				findings.append(
					self._build_finding(
						check_code=self.DECORATIVE_IMAGE_MISSING_MARKER,
						image=image,
						severity="MEDIUM",
						description="Decorative image is not properly marked as decorative",
						recommendation="Set decorative marker/tag for non-informative image",
					)
				)
		return findings

	def _check_image_without_tag(self, images: list[dict[str, Any]]) -> list[dict[str, Any]]:
		findings: list[dict[str, Any]] = []
		for image in images:
			has_tag = image.get("has_figure_tag")
			if has_tag is False:
				findings.append(
					self._build_finding(
						check_code=self.IMAGE_WITHOUT_TAG,
						image=image,
						severity="HIGH",
						description="Image exists in PDF but semantic figure tag is missing",
						recommendation="Tag image as Figure in the PDF structure tree",
					)
				)
		return findings

	def _check_low_quality_alt_text(self, images: list[dict[str, Any]]) -> list[dict[str, Any]]:
		findings: list[dict[str, Any]] = []
		for image in images:
			if self._is_decorative(image):
				continue

			alt_text = image.get("alt_text")
			if alt_text is None:
				continue

			normalized = self._normalize_text(alt_text)
			if not normalized:
				continue

			if normalized in self._LOW_QUALITY_ALT_TERMS:
				findings.append(
					self._build_finding(
						check_code=self.LOW_QUALITY_ALT_TEXT,
						image=image,
						severity="MEDIUM",
						description=f'Low quality alt text detected: "{str(alt_text).strip()}"',
						recommendation="Replace with specific alt text describing the image purpose",
					)
				)
		return findings

	def _is_decorative(self, image: dict[str, Any]) -> bool:
		return image.get("is_decorative") is True or image.get("decorative") is True

	def _build_finding(
		self,
		check_code: str,
		image: dict[str, Any],
		severity: str,
		description: str,
		recommendation: str,
	) -> dict[str, Any]:
		return {
			"agent_code": self.agent_code,
			"check_code": check_code,
			"page": image.get("page"),
			"element_id": image.get("element_id"),
			"severity": severity,
			"status": "FAILED",
			"description": description,
			"recommendation": recommendation,
		}

	@staticmethod
	def _normalize_text(value: Any) -> str:
		return str(value).strip().lower()
