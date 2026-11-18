# Book Forge — End-to-End Runbook

From an empty database to a downloadable Blueprint PDF. Every endpoint below is
prefixed `/api/v1/book-forge`. Verified against the router as built.

---

## Step 0 — One-time setup (per environment)

Run once. Without these the pipeline fails with a clear 409 telling you which is
missing.

```bash
# Structure extraction prompt — reads a syllabus into unit -> chapter
venv\Scripts\python scripts\seed_syllabus_structure_prompt.py

# Chapter prose prompt — writes each chapter from retrieved source material
venv\Scripts\python scripts\seed_chapter_content_prompt.py

# Blueprint prompt family (legacy; see Gotcha 1)
venv\Scripts\python scripts\seed_blueprint_prompts.py
venv\Scripts\python scripts\seed_blueprint_prompts_v2.py
```

`.env` must have `OPENAI_API_KEY` (embeddings) and `PINECONE_API_KEY` (vector
store). Without them the embedding and vector-store stages **skip silently** and
retrieval later returns nothing.

The `book_forge_audit_sheets` table is created automatically by
`Base.metadata.create_all()` on startup. For production, apply
`scripts/migrate_audit_sheets.sql`.

---

## Step 1 — Define the category (book type)

```
POST /categories
{ "category": "UPSC Geography", "category_description": "Optional paper, Geography" }
```

`category` is free text, normalised server-side (`"UPSC Geography"` →
`upsc_geography`). Returns `category_id`.

The category is what selects book-type-specific prompts later:
`syllabus_structure_upsc_geography` is preferred over the base
`syllabus_structure` when it exists.

```
GET  /categories                      list
GET  /categories/{category_id}        one
```

---

## Step 2 — Define guidelines for that book type

```
GET  /prompts/book-types                      what's configured
GET  /prompts/book-types/{category_id}        current guidance
POST /prompts/book-types/{category_id}/preview   dry-run the composed prompt
PUT  /prompts/book-types/{category_id}
{ "guidance": "plain-English rules for this book type",
  "model": "gpt-4o",          // optional per-book-type model override
  "created_by": 1 }
POST /prompts/book-types/{category_id}/revert     back to the previous version
```

Guidance is versioned — a PUT creates a new version and archives the old one, so
this is safe to iterate on.

> **Read Gotcha 1 before relying on this step.** These endpoints currently edit
> the `blueprint_generation` template, which the rewritten generation path no
> longer calls.

**You can skip this step.** Every prompt has working default guidance; the base
template applies when no category-specific one exists.

---

## Step 3 — Create the project

```
POST /projects
{ "book_title": "Geography Optional Paper-1",   // required
  "created_by": 1,                               // required
  "category_id": 3,
  "book_subject": "Geography",
  "target_audience": "UPSC aspirants",           // drives depth calibration
  "language_code": "en",
  "expected_pages": 600,
  "publisher_name": "...",
  "primary_output_format": "pdf",
  "book_description": "..." }
```

Only `book_title` and `created_by` are required. `book_status` is **not**
settable — projects always start in `draft` and advance through the workflow.

Note `chapter_count` is accepted by the schema but **no longer used** for
generation: chapter count is derived from the syllabus. Leave it null.

```
GET    /projects                    list (supports skip/limit/book_status)
GET    /projects/{project_id}       one
PUT    /projects/{project_id}       update metadata
DELETE /projects/{project_id}       soft delete
```

---

## Step 4 — Upload source documents

```
POST /projects/{project_id}/documents      (multipart/form-data)
  files          = one or more files
  created_by     = 1
  document_type  = "syllabus"        <-- REQUIRED for the syllabus
```

**The syllabus must be tagged `document_type="syllabus"`.** Structure extraction
looks for exactly this tag and returns 409 if it finds nothing. This is
deliberate: falling back to "every document" would blend the SME interview and
previous-year questions into the chapter list.

Upload three kinds of material, in separate calls so each gets the right tag:

| What | `document_type` | Why |
|---|---|---|
| Syllabus | `syllabus` | the chapter structure is read from this |
| Previous-year questions | `pyq` | reference/intelligence signal |
| Books, notes, reference material | (anything, e.g. `reference`) | **this is what chapters are written from** |

> **Reference material is not optional in practice.** A syllabus lists topic
> *names*; it does not explain them. With only the syllabus and PYQ ingested,
> per-chapter retrieval has almost nothing to return and chapter summaries come
> back thin. See Gotcha 3.

Each file is processed independently — one bad file does not fail the batch. The
first successful upload advances the project `draft` → `sources_added`.

```
GET    /projects/{project_id}/documents        list
GET    /documents/{document_id}                metadata
GET    /documents/{document_id}/download       download
GET    /documents/{document_id}/preview        inline
DELETE /documents/{document_id}                soft delete + remove from disk
```

---

## Step 5 — SME interview (optional)

```
POST /projects/{project_id}/interview      (multipart/form-data)
  created_by = 1
  text       = "..."          OR
  file       = <text or PDF>
```

Stored as `sme_interview_<datetime>.pdf` in the project's documents, so it flows
into the knowledge base like any other source.

---

## Step 6 — Build the knowledge base

```
POST /projects/{project_id}/process
```

Runs the book-processing graph:

```
parser -> knowledge_graph -> chunking -> embeddings -> vector_store (Pinecone)
```

Advances `sources_added` → `processing` → `knowledge_ready`. Synchronous and can
take a minute (Pinecone index creation on first run is slow). Response reports
`chunks`, `embeddings`, `vector_ids` and anything `skipped`.

**Check `chunks` in the response.** If it's single digits, your corpus is too
small for per-chapter retrieval to do anything useful — go back to Step 4.

---

## Step 7 — Generate the audit sheet

```
POST /projects/{project_id}/audit-sheet        (NO request body)
```

The system reads the structure itself:

```
syllabus document(s) -> parser -> structure prompt -> LLM extracts an
n-level tree of verbatim labels -> every label verified against the source
-> chapter rows + ambiguity flags -> versioned .xlsx
```

- **409** — no document tagged `document_type='syllabus'`
- **409** — the `syllabus_structure` prompt is not seeded (Step 0)
- **422** — the syllabus could not be parsed into text (a scanned PDF needs OCR)
- **201** — returns `version`, `row_count` and a `download_url`

Any chapter label the model returned that does **not** appear verbatim in the
syllabus is kept but flagged on the *Parse Flags* tab, so the SME sees exactly
what could not be confirmed.

---

## Step 8 — SME reviews and submits

```
GET /projects/{project_id}/audit-sheet/download                 latest generated
GET /projects/{project_id}/audit-sheet/download?version=1       any version
```

The SME edits **only the yellow columns**:

| Column | Meaning |
|---|---|
| `Keep? (Y/N)` | `N` drops a row that is not a real chapter |
| `Corrected chapter title` | overrides our wording where it's wrong |
| `SME weight (1-5)` | relative importance; blank = held as unweighted |
| `SME notes` | anything missing or mis-scoped |

Then upload it back:

```
POST /projects/{project_id}/audit-sheet/submit     (multipart/form-data)
  file       = <the filled .xlsx>
  created_by = 1
  notes      = "optional"
```

Rejected with **400** if the workbook isn't an audit sheet, has no chapter rows,
or was generated for a different project — the README carries a hidden identity
block that ties it back to the exact generated version.

The response `summary` confirms the round-trip landed:
`{rows, kept, dropped, weighted, retitled, match_verdicts}`.

```
GET /projects/{project_id}/audit-sheet/versions            full history
GET /projects/{project_id}/audit-sheet/{version}           one version + payload
```

Versions are one monotonic sequence across both directions, so the history reads
as a conversation: `v1 generated → v2 submitted → v3 generated → v4 submitted`.

---

## Step 9 — Generate the blueprint

```
POST /projects/{project_id}/blueprint
{ "created_by": 1, "sme_emphasis": "optional overall emphasis note" }
```

Returns **202 Accepted** with `blueprint_id`, `version` and `status_url`.

- **409** — project not in `knowledge_ready` / `blueprint_ready` (run Step 6)
- **409** — no submitted audit sheet (run Step 8) ← *the structural gate*

What runs in the background, per chapter the SME kept:

```
chapter title + unit -> embed -> vector search (top_k=6)
                     -> batched LLM call (8 chapters per call)
                     -> summary, learning_objectives, covered_topics, key_concepts
```

Structure is not negotiable: chapters are matched by position and titles are
overwritten with the SME-approved wording, so the model cannot add, drop, rename,
merge or reorder anything.

### Poll for completion

```
GET /projects/{project_id}/blueprint
```

Read `status`:

| `status` | Meaning |
|---|---|
| `generating` | still running |
| `generated` | done |
| `approved` | done, and the review agent approved it |
| `failed` | `blueprint_json.error` says why |

Job state lives on the blueprint **row**, so polling survives a restart and works
with more than one worker.

Also in `blueprint_json`:

- `units[]` — units as Parts, each with its `chapters[]`
- `ungrounded_chapters[]` — chapters retrieval found no source material for
- `audit_sheet_version` — which signed-off sheet this was built from
- each chapter carries `weight`, `grounded` and `source_document_ids`

```
GET /projects/{project_id}/blueprints        all versions
```

---

## Step 10 — Download the Blueprint PDF

```
GET /projects/{project_id}/blueprint/pdf                 latest
GET /projects/{project_id}/blueprint/{version}/pdf       a specific version
```

---

## Project status machine

```
draft -> sources_added -> processing -> knowledge_ready
      -> generating_blueprint -> blueprint_ready
                             -> failed
```

Transitions are forward-only. A 409 mentioning status means you skipped a step.

---

## The happy path, condensed

```
POST /categories                                  -> category_id
POST /projects                                    -> project_id
POST /projects/{id}/documents   (syllabus)                     document_type=syllabus
POST /projects/{id}/documents   (pyq, reference material)
POST /projects/{id}/interview   (optional)
POST /projects/{id}/process                       -> knowledge_ready
POST /projects/{id}/audit-sheet                   -> 201, version N
GET  /projects/{id}/audit-sheet/download           # SME fills it in
POST /projects/{id}/audit-sheet/submit            -> 201, version N+1
POST /projects/{id}/blueprint                     -> 202
GET  /projects/{id}/blueprint                      # poll until status != generating
GET  /projects/{id}/blueprint/pdf                 -> PDF
```

---

## Gotchas

**1. The guidance endpoints currently edit a template the generator no longer
uses.** `PUT /prompts/book-types/{category_id}` writes guidance into the
`blueprint_generation` template (via `blueprint_prompt_admin`). Since generation
was split into structure extraction + per-chapter prose, the agent reads
`chapter_content` instead. **Editing guidance through the API therefore has no
effect on output today.** Until this is repointed, change guidance by editing
`DEFAULT_GUIDANCE` in `scripts/seed_chapter_content_prompt.py` (prose/depth) or
`scripts/seed_syllabus_structure_prompt.py` (what counts as a chapter) and
re-running the script. This should be fixed.

**2. `chapter_count` on the project is vestigial.** It used to cap the chapter
count and caused the original units-as-chapters bug. Chapter count now comes from
the syllabus. Leave it null.

**3. Chapters can only be as good as the corpus.** Retrieval draws on whatever was
ingested. With only a syllabus and PYQ in the vector store there is nothing that
*teaches* a topic, so summaries will be thin and `ungrounded_chapters` long. That
is the system reporting honestly, not a bug — the fix is uploading reference
material and re-running Step 6.

**4. PYQ frequency is not yet measured.** The audit sheet's `PYQ hits` column
reads 0 for every chapter, with a note on the README saying so. Weighting is the
SME's until the frequency signal is built.

**5. Blueprint generation runs in the web process** via `BackgroundTasks`, so it
competes with request handling. Fine at low load; a real queue is the next step at
100+ chapters.

**6. Known bug — the knowledge graph is discarded.** `GraphValidator` rejects an
entire graph over a single self-loop (`Self-loop on node 'tcpdf'` — PDF producer
metadata being extracted as a domain entity), so 600+ nodes are thrown away each
run. It does not block the blueprint path.
