"""
alt_placeholder.py

One definition of "this /Alt is not a real description".

WHY THIS EXISTS
---------------
The pipeline writes a provisional marker — "[TO BE DESCRIBED]" — whenever
alt_text_sanitizer (step 11) cannot derive a description and alt_vision_suggester
(step 11.5) cannot generate one.  That is the correct behaviour: inventing a
description would be worse than admitting the gap.

The problem was that the marker was recognised in three different places with
three different definitions, and the one that fed the customer-facing report was
the weakest:

    accessibility_linter._PLACEHOLDER   regex, catches it        (report-only)
    alt_text_sanitizer.RE_PLACEHOLDER   regex, different shape   (internal)
    image_accessibility_agent._GENERIC  exact-match word set     (THE REPORT)

`"[TO BE DESCRIBED]".lower()` is not in {"image", "photo", "figure", …}, so
IMG-002 PASSED on a figure whose /Alt was literally the pipeline's own
placeholder.  A failed vision call was reported to the caller as clean alt text.

So the rule lives here, once.  If the marker ever changes, every consumer that
imports from this module follows it automatically.
"""

from __future__ import annotations

import re

# The marker alt_text_sanitizer writes when no description could be derived.
# Kept identical to alt_text_sanitizer.PROVISIONAL.
PROVISIONAL = "[TO BE DESCRIBED]"

# Single generic words that describe nothing. Matched whole-string.
GENERIC_WORDS = {
    "image", "photo", "picture", "figure", "image1", "img", "graphic",
    "pic", "chart", "diagram", "screenshot", "logo", "icon", "illustration",
}

# Templated / unfinished-work markers, anywhere in the string.  "to be
# described" first because that is the one the pipeline itself emits.
RE_PLACEHOLDER = re.compile(
    r"to\s*be\s*(described|added|written|completed|determined)"
    r"|placeholder"
    r"|\btodo\b"
    r"|\btbd\b"
    r"|\bxxx+\b"
    r"|description\s+(needed|required|pending)"
    r"|\balt\s*text\b"
    r"|\bno\s+description\b",
    re.I,
)

# A bare figure label carrying no description: "Figure", "Fig. 3", "Image 12".
RE_BARE_LABEL = re.compile(
    r"^\W*(fig(ure)?|image|graphic|picture|img|pic|table|photo|chart)?\.?\s*[\d.\-]*\W*$",
    re.I,
)


def is_placeholder_alt(alt) -> tuple[bool, str]:
    """Is *alt* a non-description?  Returns (verdict, human-readable reason).

    The reason is written to be shown to the caller in the IMG-002 message, so
    it names WHAT was wrong rather than just saying the check failed.
    """
    if alt is None:
        return False, ""          # absent /Alt is IMG-001's business, not this check

    text = str(alt).strip()

    if not text:
        return True, "Empty /Alt attribute"

    # Strip a trailing NUL — some producers pad /Alt strings with one, and it
    # would otherwise defeat the exact-match tests below.
    text = text.rstrip("\x00").strip()
    if not text:
        return True, "Empty /Alt attribute"

    if text == PROVISIONAL:
        return True, (
            f"Unresolved pipeline placeholder /Alt: '{text}' — alt-text generation "
            f"did not complete for this figure"
        )

    if RE_PLACEHOLDER.search(text):
        return True, f"Placeholder /Alt: '{text[:60]}'"

    if text.lower() in GENERIC_WORDS:
        return True, f"Generic placeholder /Alt: '{text}'"

    if RE_BARE_LABEL.match(text):
        return True, f"Bare figure label as /Alt, no description: '{text}'"

    return False, ""
