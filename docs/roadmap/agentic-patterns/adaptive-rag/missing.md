# Adaptive RAG: Missing Functionality

## P0 — Blocking

### 1. Max-iteration guard not enforced

**Current state**: `FlowCompiler(max_iterations=100)` stores the limit but
never checks it. Generated loop-back routers have no iteration counter or
guard. An evaluator that always returns `coverage < 0.85` loops forever.

**Files**:
- `src/asya-lab/asya_lab/flow/compiler.py:52-57` — `max_iterations` parameter
  stored but unused
- `src/asya-lab/asya_lab/flow/codegen.py:724-771` — `_emit_loop_router()` has
  no iteration limit logic

**What's needed**:
- Compile-time: inject `__asya_iter` counter increment into loop routers
- Runtime: sidecar or router checks `__asya_iter >= max_iterations` and breaks
- Configurable per-flow: `@flow(max_iterations=5)`
- On exhaustion: route to configurable handler (escalation actor or x-sump)

### 2. Fan-in timeout for retriever fan-out

Same as document-processing/missing.md#1. If one retriever hangs (e.g., Jira
API is down), the entire fan-in waits indefinitely.

---

## P1 — Important

### 3. No incremental context accumulation across loop iterations

**Current state**: Each loop iteration replaces `p["chunks"]` with the new
fan-out result. Previous iteration's chunks are lost unless the flow
explicitly copies them.

**What's needed**:
- Accumulation mode for fan-out results: `p["all_chunks"] += p["chunks"]`
  (append across iterations, not replace)
- This is the `async for event in actor(state)` pattern from the agentic
  umbrella ADR — accumulate events into a payload field across loop iterations

**Files**:
- `.aint/aints/agentic-umbrella/adr.asya-csp-vs-adk-async-generator-for-agentic.md`
  Section 5 — designed but not implemented
- `src/asya-lab/asya_lab/flow/codegen.py` — no accumulation codegen

**Workaround**: Users manually write `p["all_chunks"] = p.get("all_chunks", []) + p["chunks"]` as a payload mutation in the flow. Works but error-prone.

### 4. No token counting for accumulated context

**Current state**: As retrieved chunks accumulate across iterations, payload
grows unboundedly. No mechanism to estimate token count or truncate.

**What's needed**:
- Event compaction actor (identified in agentic umbrella as open task
  `open.1m0g.research-event-compaction-context-window-management.md`)
- Token budget parameter on generators: actor trims context to fit window
- Sliding window strategy: keep N most recent/relevant chunks

### 5. No embedding/vector search integration

**Current state**: State-proxy stores raw files (JSON, binary). No built-in
semantic search over stored documents. Each retriever must implement its own
embedding + similarity logic.

**What's needed** (optional — can be external):
- State-proxy metadata for embeddings (store embedding vectors as xattr)
- Or: document that vector search is out of scope — use external vector DB
  (Pinecone, Weaviate, pgvector) as a tool inside retriever actors

---

## P2 — Nice to Have

### 6. No source attribution in fan-in results

**Current state**: Fan-in merges results into a list but doesn't tag which
retriever produced which chunk.

**What's needed**:
- Fan-in metadata: each slice tagged with source actor name
- Generator can cite sources: "According to Confluence [chunk 3]..."
