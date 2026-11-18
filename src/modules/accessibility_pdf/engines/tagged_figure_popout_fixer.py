#!/usr/bin/env python3
"""
tagged_figure_popout_fixer.py

Post-processing fixer for the Orion accessibility remediation pipeline.

Clears the PDF/UA error:
    "Tagged content present inside an artifact"
(PAC: PDF/UA -> Content -> Tagged content inside artifacts)

Why this is a SEPARATE fixer from figure_association_fixer.py
-------------------------------------------------------------
figure_association_fixer.py handles ORPHAN figures — <Figure> tags that have
NO /K content link — and wraps their image in tagged marked content, popping
them out of any enclosing artifact as it goes.

This fixer handles the other case: figures that are ALREADY associated (their
/K points at real MCID content) but whose marked content sits INSIDE an
/Artifact block in the page content stream. That nesting is the PDF/UA
violation. Because the figure already has an MCID, figure_association_fixer
reports "0 orphans" and skips it — so this pass is needed to catch them.

What it does
------------
Walks each page content stream tracking the marked-content stack. When a tagged
block (a BDC carrying an /MCID, tag != /Artifact) opens while one or more
/Artifact blocks are open, it "pops the block out":
  1. finds the block's matching EMC (depth-balanced),
  2. closes every currently-open marked-content block,
  3. re-emits the tagged block at top level (outside the artifact),
  4. reopens the previously-open blocks, preserving surrounding artifact content.

The image still renders identically; only its marked-content nesting changes.

Convention
----------
    python3 tagged_figure_popout_fixer.py <input.pdf> <output.pdf>
Exit 0 + non-empty output signals success. Nothing to do -> valid copy, exit 0.

Requires: pikepdf
"""

from __future__ import annotations

import sys

try:
    import pikepdf
    from pikepdf import Operator
except ImportError:  # pragma: no cover
    print("tagged_figure_popout_fixer: pikepdf is required", file=sys.stderr)
    sys.exit(1)


def _tag_of(mc_op):
    """Tag name of a marked-content opening op, e.g. '/Artifact' or '/Figure'."""
    operands, _operator = mc_op
    return str(operands[0]) if operands else None


def _has_mcid(operands):
    return (len(operands) >= 2
            and isinstance(operands[1], pikepdf.Dictionary)
            and '/MCID' in operands[1])


def fix_pdf(in_path, out_path):
    """Pop tagged blocks out of enclosing artifacts. Returns count popped."""
    pdf = pikepdf.open(in_path)
    total = 0

    for pnum, page in enumerate(pdf.pages):
        try:
            ops = list(pikepdf.parse_content_stream(page))
        except Exception as exc:
            print(f"tagged_figure_popout_fixer: page {pnum+1} parse failed: "
                  f"{exc}; skipping")
            continue

        new_ops = []
        mc_stack = []          # (operands, operator) of currently-open BDC/BMC
        i, n = 0, len(ops)
        changed = False

        while i < n:
            operands, operator = ops[i]
            o = str(operator)

            if o in ('BDC', 'BMC'):
                tag = str(operands[0]) if operands else '?'
                is_tagged = (o == 'BDC' and _has_mcid(operands))
                inside_artifact = any(_tag_of(m) == '/Artifact' for m in mc_stack)

                if is_tagged and tag != '/Artifact' and inside_artifact:
                    # find this block's matching EMC (depth-balanced)
                    depth, j = 0, i
                    while j < n:
                        oj = str(ops[j][1])
                        if oj in ('BDC', 'BMC'):
                            depth += 1
                        elif oj == 'EMC':
                            depth -= 1
                            if depth == 0:
                                break
                        j += 1
                    block = ops[i:j + 1]           # full BDC..EMC of the figure

                    # close every open marked-content block (innermost first)
                    for _ in range(len(mc_stack)):
                        new_ops.append(([], Operator('EMC')))
                    # emit the tagged block at top level (outside artifact)
                    new_ops.extend(block)
                    # reopen the blocks we closed, in original order
                    for m in mc_stack:
                        new_ops.append(m)

                    total += 1
                    changed = True
                    i = j + 1                        # skip past the popped block
                    continue
                else:
                    mc_stack.append((operands, operator))
                    new_ops.append((operands, operator))

            elif o == 'EMC':
                if mc_stack:
                    mc_stack.pop()
                new_ops.append((operands, operator))

            else:
                new_ops.append((operands, operator))

            i += 1

        if changed:
            page.Contents = pdf.make_stream(pikepdf.unparse_content_stream(new_ops))

    pdf.save(out_path)
    print(f"tagged_figure_popout_fixer: popped {total} tagged block(s) out of "
          f"artifacts")
    return total


def main(argv):
    if len(argv) != 3:
        print("Usage: python3 tagged_figure_popout_fixer.py <input.pdf> "
              "<output.pdf>", file=sys.stderr)
        return 2
    try:
        fix_pdf(argv[1], argv[2])
        return 0
    except Exception as exc:  # pragma: no cover
        import traceback
        print(f"tagged_figure_popout_fixer: FAILED: {exc}\n"
              f"{traceback.format_exc()}", file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
