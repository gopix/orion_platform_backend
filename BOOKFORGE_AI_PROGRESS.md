# BookForge AI — Build Progress & Handoff Notes

_Last updated: 2026-08-07_

A running record of the `src/modules/book_forge/ai/` build so we can resume the conversation.

## Architecture / layering

The `ai/` package was reorganized into layers:

```
ai/
├── foundation/     llm, prompts, chunking, embeddings, vector_store
├── intelligence/   parsers, knowledge_graph, memory, evaluation, guardrails
├── orchestration/  agents, langgraph, workflow_state, orchestrators, services, models, exceptions
├── integration/    tools, mcp
└── shared/         models, constants, enums, exceptions
```

Only `foundation/` submodules have substantial code from earlier; everything under
`intelligence/` is what we've been building. `memory` is still empty scaffolding.

## House conventions (followed throughout)

- **Pydantic v2** data models, `model_config = {"from_attributes": True}`, computed fields where useful.
- **One class per file**; package `__init__.py` re-exports.
- **Exceptions**: base `<Module>Exception` with `message` / `error_code` (e.g. `CHUNK-001`) / `details` / `cause` and a `[CODE] msg (details)` `__str__`. Subtypes for "invalid/resolution" and "validation".
- **Services** are orchestration-only: `validate → factory/dispatch → do work → return result`, one structured log line, a shared singleton (e.g. `parser_service`), collaborators injectable.
- **Providers/strategies** use a base ABC + a factory keyed by an enum/name.
- **Utils** are stateless/pure; heuristic baselines are documented as the seam where an LLM/model plugs in later behind the same interface.
- Reuse across modules: `TokenEstimator`, `TextNormalizer`, `SentenceExtractor` live in `foundation/chunking/utils` and are reused by embeddings, guardrails, evaluation, etc.

## Completed modules

### foundation/chunking — COMPLETE
models, strategies (heading=default, paragraph, fixed, semantic=stub raising NotImplementedError),
factory (`ChunkStrategyFactory`), service (`chunking_service`), utils (TokenEstimator, TextNormalizer,
HeadingDetector, ParagraphExtractor, SentenceExtractor, ChunkStatisticsCalculator), exceptions
(`ChunkingException`, `InvalidChunkStrategyException`, `ChunkValidationException`).

### foundation/embeddings — COMPLETE
models (EmbeddingRequest consumes Chunks, EmbeddingVector w/ computed dimension, EmbeddingUsage,
EmbeddingResponse+EmbeddingStatistics), providers (base + OpenAI, batching + error translation),
factory, service (`embedding_service`), utils (EmbeddingStatisticsCalculator), exceptions
(`EmbeddingException`, `InvalidEmbeddingProviderException`, `EmbeddingValidationException`).

### foundation/vector_store — COMPLETE  (renamed from `vectordb`)
models (VectorStoreRequest holds `List[EmbeddingVector]`, VectorStoreResponse, VectorSearchRequest,
VectorSearchResult), providers (base + Pinecone, no SDK leakage), factory, service
(`vector_store_service`: store/search/delete/delete_namespace), utils (MetadataBuilder), exceptions
(`VectorStoreException` base, `InvalidVectorProviderException`, `VectorSearchException`).

### intelligence/parsers — COMPLETE
models (ParsedDocument, DocumentMetadata+DocumentFormat enum, DocumentSection (nested), DocumentParagraph,
DocumentTable, DocumentImage), providers (base + PDF via pdfplumber + DOCX via python-docx; EPUB intentionally
not created), factory (`ParserProviderFactory`), service (`parser_service`), utils (FileTypeDetector,
DocumentStatistics), exceptions (`ParserException`, `UnsupportedDocumentException`, `DocumentParsingException`).
NOTE: needs `pdfplumber` + `python-docx` in requirements.txt.

### intelligence/knowledge_graph — COMPLETE
models (GraphNode+NodeType, GraphEdge, Entity+EntityType, Concept, RelationshipType, KnowledgeGraph w/
SerializeAsAny nodes), extractors (Entity/Concept/Relationship — heuristic baselines, LLM seam),
builder (`GraphBuilder`: merge dupes, remap label/id edges), validators (`GraphValidator`),
repositories (`BaseGraphRepository` + `JsonGraphRepository`), utils (GraphStatistics, GraphSerializer
JSON/GraphML/Cypher, NodeMerger), service (`knowledge_graph_service`), exceptions
(`KnowledgeGraphException`, `EntityExtractionException`, `RelationshipExtractionException`,
`GraphValidationException`).

### intelligence/guardrails — COMPLETE
models (GuardrailRequest, GuardrailResponse w/ modified_prompt/output + risk, ValidationResult+
ValidationStatus+Severity, PolicyResult, RiskResult+RiskLevel+RiskDecision), validators (Input/Prompt/
Output/Json), policies (base + PII, PromptInjection, Publisher, OutputLength), processors (PromptSanitizer,
OutputCleaner, JsonRepair), utils (RiskCalculator — severity-driven, wired into service; PolicyLoader —
JSON/YAML/dict, currently unused by choice), service (`guardrail_service.run()`: input validation → policy
checks → prompt sanitization → LLM(callable) → output validation → output repair → RiskCalculator →
GuardrailResponse; decision drives `allowed`), exceptions (`GuardrailException`, `PolicyViolationException`,
`ValidationException`).

### intelligence/evaluation — IN PROGRESS
DONE:
- models (EvaluationRequest+AIModule enum [parser/chunking/embeddings/vector_store/prompt/guardrails/llm/
  retrieval/knowledge_graph], EvaluationResult, EvaluationMetric, ScoreCard)
- evaluators (Prompt, Chunk, Retrieval, Response, Graph — heuristic baselines; share `_common.py`)
- exceptions (`EvaluationException`, `MetricCalculationException`, `BenchmarkException`)
- service (`evaluation_service`: validate → dispatch by AIModule → evaluator → ensure ScoreCard → result;
  wraps evaluator failures in MetricCalculationException; `evaluate_all()` batch)
- validators (`EvaluationValidator`: valid request / supported evaluator / required data — wired into service)

NOT DONE (empty dirs): `metrics/`, `benchmarks/`

### orchestration — COMPLETE (core wiring)
- **models/** (shared orchestration DTOs): AgentRequest, AgentResponse, WorkflowRequest, WorkflowResult,
  WorkflowContext (blackboard w/ get/set/update/record_step).
- **workflow_state/**: BaseWorkflowState (status enum PENDING/RUNNING/PAUSED/COMPLETED/FAILED/CANCELLED +
  advance/add_message/fail/complete helpers), InterviewState, BlueprintState, ReviewState, ExportState,
  **ProcessingWorkflowState** (documents → parsed_documents → knowledge_graph → chunks → embeddings →
  vector_ids, + `skip()`).
- **agents/** (BaseAgent template = advance→execute→capture-error; optional injected `llm`):
  business agents SMEInterview/BlueprintGeneration/Review/Export (heuristic + LLM seam) AND processing agents
  ParserAgent/KnowledgeGraphAgent/ChunkingAgent/EmbeddingAgent/VectorStoreAgent (wrap the AI SERVICE singletons;
  embed/VDB gated on settings → skip-and-record when unconfigured).
- **langgraph/exceptions/**: GraphExecutionException (base) + InvalidGraphException + NodeExecutionException.
- **langgraph/graphs/**: private `_state_graph.py` runtime (StateGraph/CompiledGraph; add_node/add_edge/
  add_conditional_edges/compile; invoke(state)->state) — STAND-IN for real langgraph. Graphs:
  build_interview_graph, build_blueprint_graph (revise loop), build_review_graph, **build_book_processing_graph**
  (parser→knowledge_graph→chunking→embedding→vector_store).
- **langgraph/nodes/**: Node wraps Agent (callable `node(state)->state`). Interview/Blueprint/Review/Export
  + Parser/KnowledgeGraph/Chunking/Embedding/VectorStore nodes.
- **langgraph/services/**: `graph_execution_service` — compile(cached)/execute/resume, register, `engine_for(name)`
  → GraphEngine adapter (WorkflowEngine protocol). Registry: interview, blueprint, review, book_processing.
- **orchestration/services/**: `workflow_service` — lifecycle (start/resume/pause/cancel) + save/load
  (InMemoryStateStore), delegates execution to an injected engine. Does NOT execute agents.
- **orchestrators/**: `BookProcessingOrchestrator` (+ singleton) — thin entry into Orchestration; wraps
  WorkflowService + `graph_execution_service.engine_for("book_processing")`; `execute(state)` / `process(project_id, documents)`.
- **exceptions/**: WorkflowException (base) + AgentExecutionException + StateException.
- Empty scaffolding: `orchestration/utils/`, `integration/tools`, `integration/mcp`, `intelligence/memory`.

## Book Processing pipeline (THE key architecture decision — senior review)

Services must NOT orchestrate AI procedurally. `process_project` routes through the whole Orchestration layer:

```
project_router POST /projects/{id}/process
  → ai_workflow_service.process_project()   (THIN: load docs, build ProcessingWorkflowState, return summary)
  → BookProcessingOrchestrator.execute(state)
  → WorkflowService.start(state)            (lifecycle/state)
  → graph_execution_service engine          (book_processing graph)
  → ParserNode → KnowledgeGraphNode → ChunkingNode → EmbeddingNode → VectorStoreNode
  → each Node wraps an Agent wraps an AI service singleton
```
- `ai_workflow_service.py` imports ONLY the orchestrator + ProcessingWorkflowState — NO parser/chunking/
  embeddings/vector/kg imports (verified). Adding OCR / parallel stages / review loop-backs = edit
  `book_processing_graph.py`, service never changes.
- Two independent workflows now: **Graph 1 Book Processing** (ingest), **Graph 2 Blueprint Generation**.
- Verified end-to-end on a real PDF: status=completed, all 5 nodes ran in order, KG 12 nodes/8 edges,
  1 chunk, embedding+vector_store skipped (no keys, recorded in `state.skipped`).

## API endpoints wired to AI (book_forge/routers + services)

- `POST /projects/{project_id}/interview` (document_router) — accepts text OR text/PDF upload; stores as
  `sme_interview_<datetime>.pdf` via `document_service.create_interview_pdf_from_text` / `store_interview_pdf`
  (reuses `create_document` → same project storage; reportlab renders text→PDF).
- `POST /projects/{project_id}/process` (project_router) — fetches docs, calls thin
  `ai_workflow_service.process_project` → Book Processing orchestration.

## Known follow-ups / decisions to revisit

- **Settings**: DONE — added to `src/core/config.py`: `openai_api_key` (existing), `embedding_provider`,
  `embedding_model`, `vector_provider`, `pinecone_api_key`, `pinecone_index`, `pinecone_cloud`, `pinecone_region`.
  Set the real secrets in `.env`. Embedding/VectorStore agents skip-and-record when the key is blank.
- **requirements.txt**: `pdfplumber`, `python-docx`, `reportlab==4.5.1` added. `pyyaml` used by PolicyLoader
  (verify it's pinned). ACTION: run `pip install -r requirements.txt` in the app env for reportlab.
- **LangGraph runtime**: `orchestration/langgraph/graphs/_state_graph.py` is a lightweight STAND-IN
  (sequential; no true parallelism/checkpoint-resume). Graph *definitions* use the LangGraph-style API, so
  swapping in the real `langgraph` package is an engine change only (graphs/agents/services unchanged).
  `WorkflowService.resume` currently re-invokes from the entry point (documented) until real checkpointing.
- **Embeddings/VectorStore execution**: only run when `OPENAI_API_KEY` / `PINECONE_API_KEY` are set; otherwise
  `process_project` completes with those stages in `state.skipped`. Fills in automatically once keys are configured.
- **process_project is synchronous** — fine for now; a large project may be slow. Candidate to move to a
  background task returning a run id + status.
- **Heuristic seams** (all documented, same interface for later LLM/model swap):
  - KG extractors (entity/concept/relationship) are regex/rule-based.
  - Guardrail injection/toxicity/PII lists are keyword baselines.
  - Evaluation ResponseEvaluator faithfulness/consistency use word-overlap grounding (penalizes long
    responses vs short context) — candidate to switch to embedding/content-word similarity.
- **Git**: the whole `book_forge/ai/` tree is UNTRACKED (never committed). Repo also has many unrelated
  pre-existing uncommitted changes. To commit just this work, scope it:
  `git add src/modules/book_forge/ai && git commit -m "..."`.
- **Guardrails**: `allowed` is now risk-based (decision != BLOCK), so low-severity-only failures may pass as
  REVIEW rather than hard-block. Confirm this is desired vs. "any FAIL blocks".
- **PromptLoader/PolicyLoader** exist but unused; fine to leave.

## Suggested next steps

1. Wire the **Blueprint Generation** workflow to an endpoint the same way Book Processing is (thin service →
   orchestrator → blueprint graph), so both graphs are reachable via API.
2. Turn on embeddings + vector store: set `OPENAI_API_KEY` / `PINECONE_API_KEY` in `.env`; the Embedding/
   VectorStore nodes then run automatically (no code change).
3. Retriever layer (RAG): query → embed → vector search → top-K chunks → prompt builder → LLM — becomes its
   own graph (Graph 3), driven identically.
4. Finish evaluation: `metrics/` + `benchmarks/` (where `BenchmarkException` is used).
5. Swap the `_state_graph.py` stand-in for real `langgraph` when parallelism/checkpointing is needed.
6. Make `process_project` a background job (run id + status endpoint).
7. `intelligence/memory` module (still empty); then a scoped git commit
   (`git add src/modules/book_forge && git commit -m "..."`).
