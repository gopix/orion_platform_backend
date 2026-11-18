#!/usr/bin/env python3
"""
nested_artifact_unwrapper.py

Removes /Artifact marked-content wrappers that are nested INSIDE tagged
(structure) content.

Why this exists
---------------
PDF/UA forbids an artifact from living inside a tagged element: content is
either real (tagged) or an artifact, never both. When an earlier step wraps a
<P> (or other structure element) around text that is still inside an
/Artifact BMC..EMC sequence, the result is:

    /P <</MCID n>> BDC          <- structure element claims MCID n
        /Artifact BMC           <- artifact wrapper still present
            (readable text) Tj
        EMC
    EMC

Two problems at once:
  1. The /Artifact marking tells assistive technology to SKIP the text, so the
     paragraph is claimed in the tree but still unreadable by a screen reader.
  2. PAC reports it as "Artifact present inside tagged content" (one error per
     nested wrapper).

Fix
---
For every /Artifact sequence that has a NON-artifact (tagged) marked-content
ancestor, delete just the artifact's opening operator (/Artifact BMC or
/Artifact <<...>> BDC) and its matching EMC. The inner content then belongs
directly to the enclosing tagged MCID, so it becomes reachable AND the PAC
error clears. No structure-tree or ParentTree change is needed: the enclosing
element already claims the MCID; we are only removing a wrapper that was
suppressing the text inside it.

Safety
------
Only artifact sequences that (a) are nested inside a tag and (b) contain
readable text are unwrapped by default. A top-level artifact (running header,
page number, decorative paint that is correctly ignored) is never touched,
because it has no tagged ancestor. Paint-only nested artifacts are left alone
unless --include-paint is passed, since silently promoting decorative paint to
content can be wrong; those rare cases are better reviewed by a human.

Usage
-----
    python3 nested_artifact_unwrapper.py <input.pdf> <output.pdf> [--include-paint]
"""

from __future__ import annotations

import json
import sys

import pikepdf

# Non-text painting operators. Text-showing operators are handled separately:
# a nested artifact that *shows text at all* (even whitespace) is text content,
# not decorative paint, and must be unwrapped so it is neither hidden nor
# flagged by PAC as "artifact inside tagged content".
_PAINT_OPS = {"S", "s", "f", "F", "f*", "B", "B*", "b", "b*", "sh", "Do",
              "re", "m", "l", "c", "v", "y", "h"}
_TEXT_OPS = {"Tj", "TJ", "'", '"'}
_WS = set(b" \t\r\n\x00\x0c")


def _op(instr) -> str:
    try:
        return str(instr.operator)
    except Exception:
        return "?"


def _is_artifact_open(instr) -> bool:
    op = _op(instr)
    if op not in ("BDC", "BMC"):
        return False
    try:
        return str(instr.operands[0]) == "/Artifact"
    except Exception:
        return False


def _shows_glyph(instr) -> bool:
    if _op(instr) not in _TEXT_OPS:
        return False
    try:
        ops = instr.operands
        b = b""
        if _op(instr) == "TJ":
            for e in ops[0]:
                if isinstance(e, pikepdf.String):
                    b += bytes(e)
        else:
            s = ops[-1]
            if isinstance(s, pikepdf.String):
                b += bytes(s)
        return any(c not in _WS for c in b)
    except Exception:
        return False


def unwrap_nested_artifacts(in_path: str, out_path: str,
                            include_paint: bool = False) -> dict:
    result = {"unwrapped_text": 0, "unwrapped_paint": 0,
              "left_paint_only": 0, "pages_changed": 0}

    pdf = pikepdf.open(in_path)

    for page in pdf.pages:
        try:
            instrs = list(pikepdf.parse_content_stream(page))
        except Exception:
            continue

        # Walk the stream tracking the marked-content stack. Each stack entry:
        #   ["tag", open_idx]                         non-artifact marked seq
        #   ["art", open_idx, has_tag_ancestor,       artifact seq
        #           has_text, has_paint]
        stack = []
        drop = set()

        for i, ins in enumerate(instrs):
            op = _op(ins)
            if op in ("BDC", "BMC"):
                if _is_artifact_open(ins):
                    has_tag_ancestor = any(s[0] == "tag" for s in stack)
                    stack.append(["art", i, has_tag_ancestor, False, False])
                else:
                    stack.append(["tag", i])
            elif op == "EMC":
                if not stack:
                    continue
                top = stack.pop()
                if top[0] == "art" and top[2]:  # artifact nested inside a tag
                    _, open_idx, _anc, has_text, has_paint = top
                    if has_text:
                        drop.add(open_idx)
                        drop.add(i)
                        result["unwrapped_text"] += 1
                    elif has_paint:
                        if include_paint:
                            drop.add(open_idx)
                            drop.add(i)
                            result["unwrapped_paint"] += 1
                        else:
                            result["left_paint_only"] += 1
            else:
                # attribute content to any open nested-in-tag artifact.
                # Any text-showing operator (even whitespace) makes the
                # artifact text content, not decorative paint.
                is_text = op in _TEXT_OPS
                is_paint = op in _PAINT_OPS
                if is_text or is_paint:
                    for s in stack:
                        if s[0] == "art" and s[2]:
                            if is_text:
                                s[3] = True
                            if is_paint:
                                s[4] = True

        if drop:
            new = [ins for j, ins in enumerate(instrs) if j not in drop]
            page.Contents = pdf.make_stream(pikepdf.unparse_content_stream(new))
            result["pages_changed"] += 1

    pdf.save(out_path)
    print(f"nested_artifact_unwrapper: unwrapped {result['unwrapped_text']} "
          f"text artifact(s) nested in tags; "
          f"{result['unwrapped_paint']} paint (include_paint={include_paint}); "
          f"left {result['left_paint_only']} paint-only untouched; "
          f"{result['pages_changed']} page(s) changed")
    return result


def main(argv):
    if len(argv) < 3:
        print("Usage: nested_artifact_unwrapper.py <in.pdf> <out.pdf> "
              "[--include-paint]", file=sys.stderr)
        return 2
    include_paint = "--include-paint" in argv[3:]
    try:
        res = unwrap_nested_artifacts(argv[1], argv[2], include_paint)
        print(json.dumps(res))
        return 0
    except Exception as exc:
        import traceback
        print(f"nested_artifact_unwrapper: FAILED: {exc}\n"
              f"{traceback.format_exc()}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
