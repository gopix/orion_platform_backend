# Color Accessibility Agent — Changes

## New files
- `src/modules/accessibility_pdf/engines/validator/color_accessibility_agent.py`
  ColorAccessibilityAgent (agent_code COLOR_ACCESSIBILITY_AGENT). One cached pdfplumber
  pass per document. Checks:
  - COLOR-001 — normal text contrast >= 4.5:1 (WCAG 1.4.3 AA), HIGH
  - COLOR-002 — large text (>=18pt / >=14pt bold) contrast >= 3:1, MEDIUM
  Contrast math imported from contrast_fixer.py so validator and fixer always agree.
- `src/modules/accessibility_pdf/engines/remediator/color_remediator_agent.py`
  ColorRemediatorAgent for COLOR-001/COLOR-002. Follows the "scheduled fix" pattern
  (like LINK-001/HDR-001): flags context, hands the validator's light-text-colour
  whitelist to the pipeline; actual fix runs in post-processing (contrast_fixer),
  outcome reconciled via scheduled_outcomes.
- `seed_color_accessibility_checks.json`
  POST to /master_accessibility_check to register both checks, then clone to
  org/project via the existing /master_accessibility_check/clone endpoint.

## Modified files
- `engines/accesibility_engine_pipeline.py` — COLOR_ACCESSIBILITY_AGENT added to
  IMPLEMENTED_AGENT_SEQUENCE and AGENT_CLASS_MAP.
- `engines/remediator/remediator_service.py` — ColorRemediatorAgent registered.
- `engines/accessibility_remediation_pipeline.py` — Step 3 now records
  scheduled_outcomes["COLOR-001"/"COLOR-002"] when a contrast fix was scheduled and
  passes context["_contrast_known_text_colors"] to fix_text_contrast.
- `engines/contrast_fixer.py` — fix_text_contrast/_patch_stream accept optional
  known_text_colors whitelist: light colours (luminance > 0.50) confirmed as TEXT by
  the validator are now darkened too (previously all light colours were skipped as
  presumed backgrounds). Colours also used as rect fills are never whitelisted.
  Self-comparison against own colour as background excluded. Backward compatible —
  without a whitelist behaviour is unchanged.

## Verified
- Round trip on a synthetic low-contrast PDF: COLOR-001/002 FAIL (2.11:1, 1.41:1) →
  fixer darkens both colours → re-validation PASS/PASS.
- Regression: light rect fills untouched when no whitelist given.
- Clean sample PDF: PASS/PASS. All touched files compile.
