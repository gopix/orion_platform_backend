# Book Forge — Session Notes (12 Aug 2026)

RAG pipeline that turns uploaded source documents (syllabus, SME interview, PYQ)
into a versioned, author-ready **Book Blueprint**. FastAPI / SQLAlchemy / MySQL.

---

## What this session covered

The main thread was getting the **Book Blueprint generation** to produce a
weightage-driven chapter plan (question counts that scale with each chapter's
importance) and then fixing a guardrail bug that blocked the `gpt-4o` output.

### 1. gpt-4o guardrail block — FIXED

**Symptom:** switching the UPSC Geography book to `gpt-4o` returned
`422 Policy violated. Guardrail blocked (valid_json)`, even though the model
had generated a valid blueprint (log showed `modified=True`, 3043 output tokens).

**Root cause:** gpt-4o wraps its JSON in a Markdown code fence (```` ```json ````).
The guardrail validated the *raw* text, which failed JSON parsing → `valid_json`
HIGH violation → block. The repair step had already produced clean JSON, but the
agent discarded it because `guard.allowed` was `False`.

**Fix** (in `blueprint_generation_agent.py`, agent code — no prompt re-PUT needed):
- Added `_strip_code_fences()` and applied it in the `_llm` adapter so the raw
  output the guardrail sees is a plain JSON object.
- Introduced `_SAFETY_RULES = {prompt_injection, unsafe_instructions,
  toxic_content, PII, pii}`. Only these hard-block generation. `valid_json` (and
  other structural flags) are treated as recoverable: use the repaired output and
  rely on the agent's own `_parse_blueprint` + `_chapter_issues` validation.

### 2. v7 blueprint review — spread is now correct

Generated cleanly through gpt-4o. Distinct weights → distinct question totals,
~2.9x range top to bottom:

| Weight | Chapters | Total questions |
|--------|----------|-----------------|
| 5/5 | Climatology, Oceanography, Economic Geography | 23 |
| 4/5 | Population & Settlement | 16 |
| 3/5 | Geomorphology, Biogeography, Environmental, Models/Theories | 15 |
| 2/5 | Perspectives in Human Geo, Regional Planning | 8 |

- This is the proportional behavior missing in v5 (flat 40) and v6 (compressed 40/50).
- Heavy chapters are the genuinely high-frequency PYQ areas → PYQ-derived
  weighting is landing sensibly.
- Chapter count justified itself: produced 10 chapters matching the actual
  UPSC Geography Paper I units (the "MAX not target" rule works — no padding).

### 3. Open bug — arithmetic mismatch in weight-2 chapters

Chapters 6 (Perspectives) and 9 (Regional Planning): by-type counts sum to **9**
(1+1+1+2+1+3) but `total_questions` says **8**, and by-difficulty also says 8.
Rule "total MUST equal sum of by_type" is violated. Every other chapter
reconciles perfectly — gpt-4o slipped on the smallest chapters.

**Recommended fix (pending):** add a three-way reconciliation check to
`_chapter_issues` — assert `sum(by_type) == total_questions == sum(by_difficulty)`
— so the repair/regeneration loop catches it or the numbers are normalized before
the blueprint is saved.

---

## Key architecture (for context)

- **Flow:** project metadata + retrieved chunks → render versioned generation
  prompt (Prompt Engine) → LLM call wrapped in guardrails → structured blueprint
  written to state → persisted as a versioned row (`book_forge_blueprints`).
- **Orchestration:** Graph → Node → Agent → services.
  `BlueprintGraph`: retrieve_knowledge → generate_blueprint → review.
- **Prompt Engine:** DB-backed, versioned. Category-specific template naming
  `blueprint_generation_<category>` with fallback to base `blueprint_generation`.
- **Composed prompt:** fixed scaffold (variables, JSON contract, weightage rules)
  + plain-English guidance (the only thing publishers edit). Scaffold *code*
  changes require restart + re-PUT of guidance to recompose the stored prompt.
- **Weightage precedence:** SME emphasis (authoritative) > PYQ frequency > explicit
  marks table > even. Per-chapter `weight` (1–5); `total_questions ≈
  questions_per_chapter × weight / 3`.
- **Model routing:** `provider_for_model` (gpt* → OpenAI, claude* → Anthropic).
  Per-book-type model override via `PUT /prompts/book-types/{category_id}`
  with `"model": "gpt-4o"`.
- **Category master:** `book_forge_category` (id, category_name, category_description)
  with a hard FK from `book_forge_projects.category_id`.

## Files touched this session

- `src/modules/book_forge/ai/orchestration/agents/blueprint_generation_agent.py`
  — fence strip + safety-rules block logic (the gpt-4o fix).

## Next steps

1. Add the three-way reconciliation check to the chapter validator.
2. Regenerate and confirm weight-2 chapters reconcile.
3. (Future) Phase 2: post-generation per-chapter SME priority override endpoint
   → regenerate → new version.
