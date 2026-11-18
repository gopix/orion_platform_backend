# Blueprint Structure & Multi-Domain Generalisation — Design Doc

Status: **decisions taken — ready to build Layer 1 + Layer 2.** See §9.
Last updated: 2026-08-17

Supersedes: `book_blueprint_design.md` §"Decided" (flat chapter schema) and §9
(storage), where they conflict. Everything else in that doc still stands — the RAG
path, the graph, the versioned prompt engine and the versioned blueprint table are
all correct and are **not** being rebuilt.

---

## 1. What went wrong

A generated Paper-1 blueprint was reviewed by an SME and rejected as generic —
"no real expertise." His specific objection: **every syllabus UNIT had been turned
into a chapter.** Geomorphology is a unit; the topics under it are the chapters.

Verified against the source syllabus PDF:

| | v7 blueprint | Actual Paper-1 |
|---|---|---|
| Units | — | 10 |
| Chapters | **10** (= the 10 unit names) | **113** |

The ten v7 "chapters" — Climatology, Oceanography, Economic Geography, Population &
Settlement, Geomorphology, Biogeography, Environmental, Models/Theories, Perspectives,
Regional Planning — are the ten unit names, one for one. The book was ~11x
under-specified.

Chapter counts per unit, parsed from the syllabus:

| Section | Unit | Chapters |
|---|---|---|
| Physical | Geomorphology | 19 |
| Physical | Climatology | 13 |
| Physical | Environmental Geography | 10 |
| Physical | Oceanography | 9 |
| Physical | Biogeography | 9 |
| Human | Population and Settlement Geography | 17 |
| Human | Economic Geography | 11 |
| Human | Perspectives in Human Geography | 9 |
| Human | Models, Theories and Laws in Human Geography | 9 |
| Human | Regional Planning | 7 |
| | **Total** | **113** |

The Geomorphology split (19 chapters) matches the SME's own list exactly, 19/19,
in his order — independent corroboration that 113 is the right granularity.

### 1.1 Why it happened

Nothing in the pipeline ever *parses* the syllabus. The PDF is chunked at ~600
tokens into undifferentiated prose, retrieved by vector similarity, and pasted into
the generation prompt as `SOURCE MATERIAL`. The LLM then **infers** structure from
prose — and the most salient headings in that prose are the numbered units. The
project's `chapter_count` (~10) then confirmed the wrong answer, because the prompt
treats it as a maximum.

Structure that exists **explicitly and unambiguously** in the source document was
being guessed at instead of read.

### 1.2 A second, independent defect found while verifying

The prompt instructs the model to derive each chapter's weight from PYQ frequency.
It does not. Measured PYQ hit counts vs the weights v7 actually assigned:

| Unit | v7 weight | Measured PYQ hits |
|---|---|---|
| Climatology | 5 | 35 |
| Economic Geography | 5 | 28 |
| **Geomorphology** | **3** | **18** — 3rd highest frequency, middling weight |
| Population & Settlement | 4 | 12 |
| Environmental Geography | 3 | 12 |
| **Oceanography** | **5** | **5** — top weight, near-lowest frequency |
| Biogeography | 3 | 5 |
| Perspectives / Regional Planning | 2 | 2 |
| **Models, Theories & Laws** | **3** | **0** — middling weight, zero PYQ presence |

Rank correlation is 0.77, which looks acceptable until the individual inversions are
read. The model was producing *plausible-looking numbers*, not counting. This is the
same failure mode as the generic prose, expressed numerically — and nobody could see
it, because nothing in the system ever counted.

### 1.3 Note on how this survived review

`book_forge_session_2026-08-12.md` records the granularity bug as a success:

> "Chapter count justified itself: produced 10 chapters matching the actual UPSC
> Geography Paper I units (the 'MAX not target' rule works — no padding)."

The unit/chapter conflation passed three senior reviews unchallenged. That is the
argument for agreeing this model on paper before building on it.

---

## 2. The governing principle

> **Structure and frequency are facts to be read and counted, not judgements to be
> inferred.**

The LLM is excellent at prose and poor at being a parser or a calculator. Split the
work accordingly:

| Concern | Owner | Why |
|---|---|---|
| Syllabus hierarchy (units, chapters) | Extraction + **verification** | Present verbatim in the source; must be exact |
| PYQ frequency per chapter | Deterministic counting | Arithmetic; must be reproducible and auditable |
| Chapter weight | Rule over measured signals + SME override | Must be explainable to an SME |
| Chapter summary, learning objectives, key concepts | **LLM** | Genuine language work |

The LLM's job shrinks to writing about a chapter whose title and weight it did not
invent.

---

## 3. The generalisation problem

The immediate fix must not be UPSC-Geography-shaped, because the next book is a
different exam entirely (e.g. JEE Physics / Chemistry).

The throwaway scripts used to produce the SME audit sheet are **not** reusable, and
should not be promoted into the codebase as-is. They hardcode:

- literal `PAPER-1` / `PAPER-2` string anchors
- the section names `Physical Geography` / `Human Geography`
- a regex stripping *Drishti IAS* page furniture (publisher-specific)
- a unit pattern assuming `N. Name: topic; topic; ...` prose
- **~50 hand-written geography synonyms** for PYQ matching — the part doing the
  actual intelligence, and worth nothing outside this subject

More importantly, a different exam will not have this **document shape**:

| | UPSC Geography Optional | JEE Physics / Chemistry |
|---|---|---|
| Hierarchy expression | Semicolon-delimited prose runs under numbered units | Already explicit outline (`1.`, `1.1`, `1.1.1`) or bullets |
| Chapter separator | `;` (and sometimes `.`) | Line / numbering — semicolons absent |
| PYQ format | Short-answer, ~8/year | MCQ with 4 options + answer key, ~90/year |
| PYQ volume | 96 total | Thousands |
| PYQ → topic mapping | Diffuse, often multi-topic | Usually one question = one topic |
| Extra hierarchy level | Paper → Section → Unit → Chapter | Chemistry adds Physical / Organic / Inorganic streams |

Conclusion: **writing a parser per syllabus does not scale, and neither does writing
a regex profile per publisher.** The design has to absorb format variation without
new code.

---

## 4. Proposed architecture

Three layers, separated by how often they change.

### 4.1 Layer 1 — the invariant engine (write once)

```
Source document
  → Structure   (n-level syllabus tree)
  → Signal      (per-chapter frequency / emphasis measurements)
  → Weight      (rule over signals + SME override)
  → Blueprint   (LLM writes prose per chapter)
```

Two decisions matter here:

**(a) Model the hierarchy as an n-level tree, not `unit → chapter`.**
Geography is Paper → Section → Unit → Chapter (4 levels). JEE Chemistry is Subject →
Stream → Unit → Topic → Subtopic (5). Hardcoding two levels guarantees we are back
here on the next book. Store a tree of `SyllabusNode`, and let the profile declare
**which depth constitutes a book chapter**.

**(b) The engine is subject-agnostic.** No subject vocabulary, no publisher strings,
no separator literals anywhere in Layer 1.

### 4.2 Layer 2 — structure extraction, made generic by verification

Neither pure regex (breaks per publisher) nor an unverified LLM (invents) is
acceptable. Use the LLM as an **extractor whose every output is verified against the
source text**:

```
1. Feed the FULL syllabus text (not retrieved chunks) to the LLM.
2. Ask only for structure: a nested tree of verbatim strings. No prose, no invention.
3. VERIFY: every extracted node label must appear verbatim (normalised for
   whitespace/case) in the source text. Reject the tree on any node that does not.
4. On rejection, retry with the failing nodes named. Bounded retries, then escalate
   to human review — never silently accept.
5. Persist the verified tree. Extraction runs ONCE per document, not per blueprint.
```

Why this is the right shape:

- **Format-agnostic** — handles prose-with-semicolons, numbered outlines and bullets
  without a per-publisher rule.
- **Hallucination-proof by construction** — a chapter that isn't in the syllabus
  cannot survive step 3. Determinism comes from *verification*, not from parsing.
- **Auditable** — the verified tree is a persisted artifact an SME signs off once,
  not a fresh guess on every generation run.

The parse ambiguities found in this syllabus (three places where a full stop is used
instead of a semicolon) are exactly the class of thing step 4 should surface to a
human rather than resolve silently.

### 4.3 Layer 3 — the signal layer: embeddings, not synonym dictionaries

**This is the change that makes the answer to "will it work for JEE?" yes.**

Replace hand-written synonym maps with the embedding stack already in the codebase:

```
1. Embed each chapter title once (same model as ingestion: text-embedding-3-small).
2. Embed each PYQ question.
3. Cosine-match each question against every chapter; above threshold => a hit.
4. Frequency = hit count. Persist hits WITH the matched question text (evidence).
```

Domain-agnostic by construction: it treats "Plate tectonics" and "Rotational
dynamics" identically, with zero hand-tuning. It reuses `embedding_service` and the
Pinecone provider that already exist. And it makes PYQ a **reusable intelligence
signal** rather than a per-subject coding exercise.

Signals are pluggable behind one interface, so SME interview emphasis, explicit marks
tables and PYQ frequency are all just signals with different authority:

```python
class ChapterSignal(Protocol):
    name: str          # "pyq_frequency" | "sme_emphasis" | "marks_table"
    authority: int     # precedence rank
    def measure(self, chapters, sources) -> dict[chapter_id, Measurement]
```

### 4.4 The SME sign-off gate

**DECIDED (§9.8):** the audit sheet stops being a one-off artifact and becomes a
generated, endpoint-backed **gate that runs before blueprint generation.**

```
POST /projects/{id}/syllabus/extract        -> extract + verify tree, persist
GET  /projects/{id}/syllabus/audit-sheet    -> generate the .xlsx from the tree + signals
POST /projects/{id}/syllabus/sign-off       -> record SME weights, structural
                                               corrections, and match verdicts
POST /projects/{id}/blueprint               -> 409 CONFLICT unless a valid
                                               sign-off exists for the current tree
```

The blueprint endpoint refusing to run without sign-off is the point. It makes the
failure that started all this — an ungrounded blueprint reaching an SME — structurally
impossible rather than merely unlikely.

The sheet already produced (`blueprint_sme_audit.xlsx`) is the reference
implementation of the `audit-sheet` response body: Chapters / Unit Summary /
PYQ Matches / Parse Flags, with SME-editable columns.

### 4.5 Fixing the `sme_emphasis` gap

Today `sme_emphasis` is a **free-text field on the HTTP request** (`project_router.py:158`),
with no code path linking it to the ingested `sme_interview_*.pdf`. If the caller
doesn't retype it, the prompt renders `SME EMPHASIS: (none provided)` — and since the
prompt makes SME emphasis the *first and authoritative* weighting signal, the most
expert input in the system silently drops out.

Under this design SME emphasis becomes a first-class signal attached to **specific
chapters**, derived from the interview document, with the payload field retained only
as an override.

---

## 5. Data model changes

### 5.1 New: `syllabus_nodes` (n-level tree)

| column | notes |
|---|---|
| `id` | PK |
| `project_id` | FK |
| `document_id` | FK — which source document it came from |
| `parent_id` | self-FK, null at root |
| `depth` | 0-based |
| `node_type` | `paper` / `section` / `unit` / `chapter` / `topic` — from profile |
| `label` | verbatim text from the source |
| `ordinal` | order within parent |
| `source_offset` | character offset in extracted text (proves grounding) |
| `is_chapter` | derived: depth == profile.chapter_depth |
| `verified_at`, `verified_by` | SME sign-off |

### 5.2 New: `chapter_signals`

| column | notes |
|---|---|
| `id` | PK |
| `syllabus_node_id` | FK → the chapter |
| `signal_name` | `pyq_frequency` / `sme_emphasis` / `marks_table` |
| `value` | numeric measurement |
| `evidence_json` | matched questions / interview excerpts — auditable |
| `computed_at` | |

### 5.3 New: `syllabus_profiles` (Layer 3 config, per book type)

| column | notes |
|---|---|
| `id` | PK |
| `category_id` | FK → `book_forge_category` |
| `level_names` | e.g. `["paper","section","unit","chapter"]` |
| `chapter_depth` | which depth is a book chapter |
| `pyq_question_pattern` | how to split the PYQ document |
| `pyq_has_options` | MCQ vs short-answer |
| `match_threshold` | cosine threshold for signal matching |
| `weight_bands` | hits → weight mapping |
| `version`, `is_active` | versioned like the prompt templates |

This deliberately extends the mechanism you already have — `book_forge_category`
plus versioned `blueprint_generation_<category>` templates with base fallback
(`resolve_template_name`) — rather than inventing a parallel one.

### 5.4 Changed: `blueprint_json` envelope

Chapters become two-level (or n-level) rather than flat:

```json
{
  "title": "...", "description": "...", "target_audience": "...",
  "estimated_length": 0,
  "units": [
    { "unit_number": 1, "unit_title": "Geomorphology", "section": "Physical Geography",
      "chapters": [
        { "chapter_number": 1, "title": "Plate tectonics",
          "syllabus_node_id": 412,
          "summary": "...", "learning_objectives": ["..."],
          "covered_topics": ["..."], "key_concepts": ["..."],
          "weight": 5, "weight_basis": "sme_emphasis",
          "signals": { "pyq_frequency": 3, "sme_emphasis": 5 },
          "assessment_plan": { "...": "..." } }
      ] } ]
}
```

`syllabus_node_id` on every chapter is the grounding link — it makes "is this chapter
real?" a joinable question instead of a judgement call. `weight_basis` records *which
signal decided* the weight, so an SME can argue with it.

`book_forge_blueprints` (versioned rows) is unchanged and remains correct.

### 5.5 Removed: `chapter_count` as an input

**DECIDED: dropped.** It is currently a project field used as a *maximum number of
chapters*, and it actively caused this bug — it told the model "about 10", and the
model obliged by promoting units to chapters.

Structure is not something the end user supplies. It is the thing they came to
BookForge to be told (§9.1). Chapter count is therefore **derived** from the verified
syllabus tree and reported back, never accepted as a constraint.

The per-chapter count that *is* surfaced is **PYQ frequency** — how many times that
chapter has historically been asked — stored as a `chapter_signals` row.

> **Do not fuse these two numbers.** PYQ frequency is *historical and measured* (how
> often it was asked). `assessment_plan.total_questions` is *forward-looking and
> generated* (how many practice questions the book should carry). They are correlated
> through weight; they are never equal. Conflating them would silently cap the book
> at ~119 questions and re-introduce exactly the class of unexplainable number this
> redesign exists to remove.

### 5.6 PYQ is a signal source, not content

PYQ documents are uploaded by the SME during knowledge acquisition (§9.6) and must be
tagged `document_type = 'pyq'` and **routed to the signal corpus, not the content
corpus.**

If PYQ text is chunked into the same namespace the blueprint retrieves `SOURCE
MATERIAL` from, past exam questions leak into chapter summaries and learning
objectives as though they were syllabus content. Ingestion must keep two logical
corpora:

| Corpus | Sources | Consumed by |
|---|---|---|
| Content | syllabus, SME interview, reference material | per-chapter RAG for prose generation |
| Signal | PYQ, marks tables | `ChapterSignal.measure()` only |

---

## 6. Impact on existing code

| File | Change |
|---|---|
| `ai/orchestration/agents/blueprint_generation_agent.py` | Stops inferring structure. Receives verified chapters + weights; writes prose only. `_chapter_issues` validates against the syllabus tree. |
| `ai/orchestration/langgraph/nodes/retrieve_knowledge_node.py` | Still does per-chapter RAG, but retrieval becomes *per chapter* (narrow, well-ranked) rather than one broad blueprint-wide query. |
| `ai/orchestration/langgraph/graphs/blueprint_graph.py` | New nodes ahead of generation: `load_structure` → `measure_signals` → `assign_weights` → `generate` → `review`. |
| `services/ai_workflow_service.py` | Unchanged in shape (stays thin). |
| `scripts/seed_blueprint_prompts_v2.py` | Generation prompt no longer asks the model to choose chapters or derive weights; both are given. |
| `core/config.py` | `BLUEPRINT_TOP_K` becomes per-chapter retrieval depth; profile carries the rest. |
| **new** `ai/intelligence/syllabus/` | extractor, verifier, tree repository |
| **new** `ai/intelligence/signals/` | `ChapterSignal` implementations + weighting service |

### 6.1 Two pre-existing bugs this work should absorb

**(a) `state.fail()` is a dead end, not a revision trigger.** The 12 Aug notes
propose adding a three-way reconciliation check (`sum(by_type) == total_questions ==
sum(by_difficulty)`) to `_chapter_issues` "so the repair/regeneration loop catches
it." It won't. `_chapter_issues` failures call `state.fail()`, and
`langgraph/graphs/_state_graph.py:60` returns immediately on `FAILED` — so `review`
never runs and the `revise` branch never fires. As written, that check would
hard-fail an otherwise-good blueprint over a ±1 arithmetic slip on one chapter.
Arithmetic mismatches should be **normalised before persist**, or routed through
`review` so the loop can act. Not `state.fail()`.

**(b) Thin or empty retrieval is invisible.** `_format_retrieved` returns
`"(no source material was retrieved for this project)"` and generation proceeds
normally — no failure, no warning, nothing in the API response. A blueprint built
from zero retrieved chunks is indistinguishable from a fully grounded one. Retrieval
count and corpus size should be persisted on the blueprint row and surfaced, with a
floor below which the run refuses.

---

## 7. Weighting model

Precedence is unchanged in *intent* from the current prompt; what changes is that
each signal is **measured, stored and attributable** rather than inferred:

1. **SME emphasis** — authoritative. Overrides everything.
2. **Measured PYQ frequency** — counted, with matched questions as evidence.
3. **Explicit marks / weightage table** — when the syllabus carries one.
4. **Even** — fallback.

Rules:

- **Zero signal ≠ unimportant.** A chapter with no PYQ hits is `unweighted — needs
  SME input`, never silently weight 1. 68 of 113 chapters are in this state with the
  current PYQ corpus.
- `weight_basis` is always recorded, so any weight can be traced to the signal that
  set it.
- Bands (hits → weight) come from the profile, not from code.

### 7.1 Threshold calibration — the SME sign-off is the gold set

**DECIDED (§9.5):** the `Correct match?` column on the PYQ Matches tab is labelled
training data. The SME is already reviewing those rows, so marking a match right or
wrong costs him nothing extra — and it gives us a real precision/recall measurement
per subject.

```
1. Run matching at the profile's default threshold.
2. SME marks matches correct / incorrect during sign-off.
3. Compute precision & recall against those labels.
4. Sweep the threshold, pick the value that maximises F1, write it back to
   syllabus_profiles.match_threshold (versioned).
5. Persist the labelled set — it is the regression fixture for future changes.
```

This turns "what threshold?" from a guess into a measurement, and it accumulates:
every book onboarded improves the calibration data for its subject.

### 7.2 PYQ corpus caveat

The PYQ set supplied is **96 General Studies Geography questions (2013–2025), not
Optional Paper-1**. GS does not examine Optional-level topics, which is why 60% of
chapters show zero hits — Geosynclines, Isostasy, Denudation chronology, the
Christaller/Losch central-place theories. This is a **data sourcing** issue, not an
algorithm issue, and the design treats PYQ as a reference signal accordingly. Optional
Paper-1 PYQ would raise coverage substantially.

---

## 8. Acceptance test: onboarding JEE Physics

The design is only right if onboarding a new book type is **configuration + one SME
sign-off**, with no code changes:

1. Insert a `book_forge_category` row for JEE Physics.
2. Insert a `syllabus_profiles` row: `level_names`, `chapter_depth`,
   `pyq_question_pattern`, `pyq_has_options=true`, `match_threshold`, `weight_bands`.
3. Optionally seed a `blueprint_generation_jee_physics` prompt template — otherwise
   the base template applies (existing fallback behaviour).
4. Upload syllabus + PYQ. Extraction runs, verification passes, SME signs off the tree.
5. Signals compute. Weights assign. Blueprint generates.

**If any step in that list requires touching Python, the design has failed** and we
should revisit before building further.

---

## 9. Decisions taken (2026-08-17, Gopal)

### 9.1 Structure determination is the product, not a configuration question

**The end user comes to BookForge to be *told* the structure.** It is not a publishing
decision to be collected from them — it is the expected output of an intelligent
system.

Consequence: BookForge reads the syllabus's **own declared hierarchy** and mirrors it.
It does not invent a different grouping, and it does not ask how many chapters are
wanted. For Paper-1 that means 10 units become **Parts** and the 113 topics become
**chapters** within them, because that is what the source document says.

This also sets the extractor's acceptance criterion: **fidelity to the source
hierarchy**, not agreement with a human's expected count.

### 9.2 `chapter_count` — dropped

Not repurposed as a unit count. Removed as an input entirely (§5.5). The per-chapter
number that gets surfaced is **PYQ frequency** — how often that chapter has
historically been asked.

`assessment_plan.total_questions` remains a **separate, forward-looking** number. How
it is derived from weight is deferred, not decided here (§9.9).

### 9.3 Assessment plan — per chapter, and per unit

Generated **per chapter**; the **unit** figure is a computed rollup of its chapters,
never independently generated.

This is also where the outstanding arithmetic bug lands. Two invariants become
*computed and enforced* rather than requested of the LLM in prose:

```
within a chapter:  sum(by_type) == total_questions == sum(by_difficulty)
within a unit:     unit.total    == sum(chapter.total for chapters in unit)
```

Normalise before persist; do not `state.fail()` (see §6.1a).

### 9.4 Zero-signal chapters — held as `unweighted`

A chapter with no measured signal is `unweighted — needs SME input`. Never defaulted
to a floor weight. 68 of 113 chapters are currently in this state.

### 9.5 Threshold calibration — SME sign-off is the gold set

The `Correct match?` verdicts collected at sign-off become the labelled set used to
tune `match_threshold` per subject. Mechanism in §7.1.

### 9.6 Optional Paper-1 PYQ — will be uploaded by the SME

Supplied during **knowledge acquisition**, as a first-class document type
(`document_type = 'pyq'`), routed to the signal corpus and *not* blended into content
retrieval (§5.6). This materially raises what the PYQ signal can carry — the 60%
zero-hit rate is an artifact of the GS-only corpus, not of the method.

### 9.7 Re-extraction invalidates

If a syllabus document is re-uploaded, the verified tree **invalidates**. Cascade:

| Artifact | On re-extraction |
|---|---|
| `syllabus_nodes` | superseded; new tree version created |
| SME sign-off | **invalidated** — must be re-obtained |
| `chapter_signals` | recomputed against the new tree |
| Existing blueprints | **retained as versions, marked `stale`** — never deleted |
| `POST /blueprint` | blocked (409) until a fresh sign-off exists |

Retaining stale blueprints rather than deleting them preserves the review history that
`book_forge_blueprints` versioning exists to provide.

### 9.8 Sign-off is an endpoint-backed gate before generation

The audit sheet is **generated before blueprint generation** and gates it. Endpoints
in §4.4.

### 9.9 Still open

- [ ] **How `assessment_plan.total_questions` is derived from weight.** Deferred by
      §9.2. Needs a rule (e.g. questions-per-weight-point, with a book-level total as
      the constraint) before the assessment plan can be generated at 113-chapter scale.
- [ ] **Do all 113 chapters get full prose in v1**, or do low-weight chapters get a
      shorter treatment? At ~113 chapters this is a real cost and latency question,
      and it interacts with `process_project` still being synchronous.

---

## 10. Deliberately out of scope

Not being rebuilt, and not up for debate in this doc: the RAG path itself, the
Graph → Node → Agent → Service layering, the versioned DB-backed Prompt Engine, the
versioned `book_forge_blueprints` table, guardrails, and the LangGraph stand-in
runtime. All of these are sound. This document changes **what is fed into**
generation, not how generation is orchestrated.

---

## 11. Next step

§9 is settled, so Layer 1 and Layer 2 can be built. Suggested order, each step
independently verifiable:

| # | Build | Verified by |
|---|---|---|
| 1 | `syllabus_nodes` + tree repository (n-level) | Round-trips the 113-chapter Geography tree |
| 2 | LLM extractor + verbatim verifier | Reproduces 113 chapters from the raw PDF, 0 unverified nodes |
| 3 | `syllabus_profiles` + a JEE profile row | §8 acceptance test passes with no code change |
| 4 | `ChapterSignal` + embedding PYQ matcher | Precision/recall measured against SME labels |
| 5 | Weighting service (`weight_basis` recorded) | Every weight traceable to a signal |
| 6 | Audit-sheet + sign-off endpoints, generation gate | `POST /blueprint` 409s without sign-off |
| 7 | Rework generation prompt + agent to consume given structure | Blueprint mirrors the signed-off tree exactly |

Step 2 has a ready-made test fixture: the SME-validated tree coming back from
`blueprint_sme_audit.xlsx` is a known-correct 113-chapter ground truth, so the
extractor can be scored against it rather than eyeballed.

**Prerequisite before step 4 carries real weight:** the Optional Paper-1 PYQ upload
(§9.6). Until then the signal layer can be built and tested, but its output stays
advisory.
