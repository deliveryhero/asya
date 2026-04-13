 ▐▛███▜▌   Claude Code v2.1.87
▝▜█████▛▘  Opus 4.6 (1M context) · API Usage Billing
  ▘▘ ▝▝    ~/asya
  ⎿  SessionStart:startup hook error

❯ evaluate how asya is compared to openclaw https://docs.openclaw.ai/concepts/architecture . openclaw is a complete agentic environment
running locally. I want to understand the place of asya in it, maybe its missing parts to implement similar functionality as claw, or maybe
the way to integrate with it and serve as a backend

● Let me research OpenClaw's architecture and review Asya's current capabilities to give you a thorough comparison.

● Let me fetch OpenClaw's documentation and review Asya's architecture in parallel.

● Fetch(https://docs.openclaw.ai/concepts/architecture)
  ⎿  Received 5.3KB (200 OK)

● Fetch(https://docs.openclaw.ai/concepts/agents)
  ⎿  Error: Request failed with status code 404

● Fetch(https://docs.openclaw.ai/concepts/tools)
  ⎿  Error: Request failed with status code 404

● Explore(Explore Asya agentic capabilities)
  ⎿  Done (23 tool uses · 80.7k tokens · 1m 18s)
  (ctrl+o to expand)

● Let me get more OpenClaw details to fill in the gaps.

● Fetch(https://docs.openclaw.ai/llms.txt)
  ⎿  Received 23.8KB (200 OK)

● Fetch(https://docs.openclaw.ai/concepts/queue)
  ⎿  Received 4.4KB (200 OK)

● Fetch(https://docs.openclaw.ai/concepts/agent-loop)
  ⎿  Received 8KB (200 OK)

● Fetch(https://docs.openclaw.ai/concepts/memory)
  ⎿  Received 3.7KB (200 OK)

● Fetch(https://docs.openclaw.ai/concepts/clawflow)
  ⎿  Error: Request failed with status code 404

● Fetch(https://docs.openclaw.ai/automation/clawflow)
  ⎿  Received 3.4KB (200 OK)

● Fetch(https://docs.openclaw.ai/concepts/context-engine)
  ⎿  Received 10.5KB (200 OK)

● Now I have a comprehensive picture of both systems. Here's the analysis:

  ---
  Asya vs OpenClaw: Architectural Comparison

  ★ Insight ─────────────────────────────────────
  These two systems solve fundamentally different problems in the agentic AI space. OpenClaw is a local-first personal AI assistant (think:
  your own Jarvis), while Asya is a distributed actor mesh for production AI workloads (think: Kubernetes-native pipeline engine). They overlap
   in the "agentic" label but occupy different layers of the stack.
  ─────────────────────────────────────────────────

  Core Architecture Comparison

  ┌─────────────────┬─────────────────────────────────────────────────┬───────────────────────────────────────────────────────────────────┐
  │    Dimension    │                    OpenClaw                     │                               Asya                                │
  ├─────────────────┼─────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────┤
  │ Philosophy      │ Centralized orchestration via Gateway daemon    │ Decentralized choreography via envelope routing                   │
  ├─────────────────┼─────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────┤
  │ Deployment      │ Single process, local-first (openclaw gateway)  │ Distributed pods on Kubernetes                                    │
  ├─────────────────┼─────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────┤
  │ Agent model     │ Single agent loop with tool calls (ReAct-style) │ Many stateless actors composing pipelines                         │
  ├─────────────────┼─────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────┤
  │ Communication   │ WebSocket RPC (req/res + events)                │ Message queues (RabbitMQ, SQS, Pub/Sub)                           │
  ├─────────────────┼─────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────┤
  │ State           │ In-process + filesystem (~/.openclaw/workspace) │ Stateless actors + state-proxy sidecar (S3/GCS/Redis)             │
  ├─────────────────┼─────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────┤
  │ Concurrency     │ Lane-aware FIFO queue (in-process)              │ Horizontal pod autoscaling via KEDA                               │
  ├─────────────────┼─────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────┤
  │ LLM integration │ Built-in agent loop with 50+ model providers    │ None — actors are plain Python functions, LLM calls are user code │
  ├─────────────────┼─────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────┤
  │ Target user     │ Individual developer / power user               │ Platform teams running production AI pipelines                    │
  └─────────────────┴─────────────────────────────────────────────────┴───────────────────────────────────────────────────────────────────┘

  Where OpenClaw Has Capabilities Asya Lacks

  1. Built-in Agent Loop & LLM Reasoning

  OpenClaw ships a complete agent runtime: prompt assembly, tool dispatch, streaming, auto-compaction, model failover across 50+ providers. The
   agent loop is a first-class primitive.

  Asya's position: Asya deliberately has no built-in LLM loop. Actors are dict → dict functions — if you want an LLM call, you write it in your
   handler. This is by design (actors are transport/LLM-agnostic), but it means every team re-implements the ReAct loop.

  2. Memory System

  OpenClaw has a sophisticated three-engine memory system (builtin SQLite, QMD with reranking, Honcho for cross-session user modeling), with
  semantic search, daily notes, and auto-save before compaction.

  Asya's position: No memory primitive. Actors can use state-proxy for persistence, but there's no semantic memory, no conversation compaction,
   no cross-session recall. Memory lives in the payload or state-proxy — unstructured.

  3. 40+ Chat Channel Integrations

  OpenClaw natively bridges WhatsApp, Telegram, Slack, Discord, Signal, iMessage, etc. — making it an omni-channel agent gateway.

  Asya's position: Asya exposes A2A and MCP protocols. Chat integrations would need to be built as gateway adapters or upstream services that
  translate chat messages into A2A calls.

  4. Context Engine with Compaction

  OpenClaw's context engine manages token budgets, assembles prompts from skills/memory/history, and runs auto-compaction with summarization.

  Asya's position: No context management — actors receive a payload dict, not a managed conversation. History is just
  payload["a2a"]["task"]["history"] — a growing list with no automatic pruning.

  5. Interactive Queue Modes (Steer/Interrupt)

  OpenClaw can interrupt a running agent, steer it with new context mid-run, or coalesce multiple messages. This enables real-time
  conversational control.

  Asya's position: Once an envelope is in the mesh, you can only pause (checkpoint to S3) or cancel. No mid-execution steering. The async,
  queue-based model trades interactivity for reliability.

  6. Local Tool Execution (Browser, Files, Shell)

  OpenClaw agents can directly manipulate the local machine — browser automation, file I/O, shell commands, screen recording, camera access via
   node capabilities.

  Asya's position: Actors run in containers. Tool execution means calling an external API or another actor. No local machine access by design
  (it's a server-side platform).

  Where Asya Has Capabilities OpenClaw Lacks

  1. Distributed Scalability

  Asya scales horizontally — each actor is an independent pod, autoscaled by KEDA based on queue depth. OpenClaw is a single-process daemon
  with in-process concurrency caps.

  2. Pipeline Composition (Flow DSL)

  Asya's Flow DSL compiles Python control flow into distributed actor networks with fan-out/fan-in, error routing, conditional branching, and
  while loops — all as CPS-transformed router actors. OpenClaw's ClawFlow is explicitly "not a workflow language" — it's a job-level tracking
  layer.

  3. Queue-Based Reliability

  Asya uses durable message queues (RabbitMQ, SQS, Pub/Sub) with retry policies, DLQ routing (x-sump), and at-least-once delivery. OpenClaw's
  in-process FIFO queue provides no persistence across restarts.

  4. Multi-Transport / Multi-Cloud

  Asya abstracts the transport layer — same actors run on RabbitMQ, SQS, or GCP Pub/Sub without code changes. OpenClaw is transport-agnostic at
   a different level (WebSocket-only internally).

  5. A2A Protocol (Agent-to-Agent)

  Asya implements the full Google A2A protocol (SendMessage, GetTask, Subscribe, pause/resume, push notifications, Agent Cards). OpenClaw uses
  a custom WebSocket RPC protocol.

  6. Kubernetes-Native Operations

  Crossplane XRDs, Helm charts, KEDA autoscaling, service mesh patterns — Asya is built for platform teams managing fleet-scale AI workloads.

  Integration Possibilities

  ★ Insight ─────────────────────────────────────
  The most natural integration is OpenClaw as frontend/orchestrator, Asya as backend execution mesh. OpenClaw excels at the "last mile" — user
  interaction, memory, channel bridging, local tools. Asya excels at "the pipeline" — reliable, scalable, multi-step processing with durable
  state.
  ─────────────────────────────────────────────────

  Option A: OpenClaw → Asya (via A2A or MCP)

  OpenClaw agents call Asya pipelines as tools. When an OpenClaw agent needs to run a complex multi-step workflow (e.g., "research this topic,
  analyze sentiment, generate report"), it dispatches to Asya via:
  - A2A: POST /a2a/ with message/send — Asya runs the pipeline, streams FLY events back
  - MCP: OpenClaw already supports MCP tools — Asya flows would appear as callable tools

  This gives OpenClaw agents access to durable, scalable pipelines without building them in-process.

  Option B: OpenClaw as a Chat Channel for Asya Gateway

  Asya's gateway could add an OpenClaw channel adapter — messages from OpenClaw's 40+ chat surfaces would translate to A2A task submissions.
  Asya processes the pipeline and returns results via A2A events, which OpenClaw routes back to the originating channel.

  Option C: Shared State via State-Proxy

  OpenClaw's memory system could write to an S3-compatible backend that Asya actors read via state-proxy. This creates a shared knowledge layer
   — OpenClaw manages user preferences/context, Asya actors consume it during pipeline execution.

  What Asya Would Need to Match OpenClaw's "Complete Agentic Environment"

  If the goal is to make Asya a self-contained agentic platform (not just a pipeline mesh):

  ┌─────────────────────────────┬──────────────┬───────────────────────────────────────────────────────────────────────────────────────────┐
  │             Gap             │    Effort    │                                      Recommendation                                       │
  ├─────────────────────────────┼──────────────┼───────────────────────────────────────────────────────────────────────────────────────────┤
  │ Agent loop primitive        │ Medium       │ Ship a reference llm-actor with configurable provider, tool registry, and loop logic. Or: │
  │ (ReAct/tool-use cycle)      │              │  integrate with an existing framework (LiteLLM for providers, simple tool dispatch).      │
  ├─────────────────────────────┼──────────────┼───────────────────────────────────────────────────────────────────────────────────────────┤
  │ Memory system               │ Medium       │ Add a memory-actor or state-proxy memory backend with semantic search. Could use SQLite + │
  │                             │              │  embeddings like OpenClaw's builtin engine.                                               │
  ├─────────────────────────────┼──────────────┼───────────────────────────────────────────────────────────────────────────────────────────┤
  │ Context/token management    │ Low-Medium   │ Add compaction logic to the flow DSL — a compact router that summarizes history when it   │
  │                             │              │ exceeds a token budget.                                                                   │
  ├─────────────────────────────┼──────────────┼───────────────────────────────────────────────────────────────────────────────────────────┤
  │ Chat channel adapters       │ Low per      │ Gateway already speaks A2A/MCP. Adding Slack/Telegram/Discord adapters to the gateway is  │
  │                             │ channel      │ incremental work.                                                                         │
  ├─────────────────────────────┼──────────────┼───────────────────────────────────────────────────────────────────────────────────────────┤
  │ Interactive steering        │ High         │ Fundamentally at odds with queue-based async model. Pause/resume is the Asya equivalent.  │
  │                             │              │ Would require a hybrid sync path.                                                         │
  ├─────────────────────────────┼──────────────┼───────────────────────────────────────────────────────────────────────────────────────────┤
  │ Local tool execution        │ N/A          │ Out of scope — Asya is server-side. But a "node" actor pattern (like OpenClaw's remote    │
  │                             │              │ nodes) could bridge to local machines.                                                    │
  └─────────────────────────────┴──────────────┴───────────────────────────────────────────────────────────────────────────────────────────┘

  Bottom Line

  Asya and OpenClaw are complementary, not competitive. OpenClaw is the best-in-class personal agent shell — interactive, local, channel-rich.
  Asya is a production pipeline mesh — distributed, durable, scalable. The strongest play is integration via A2A/MCP, where OpenClaw provides
  the user-facing agentic experience and Asya provides the backend execution fabric for complex multi-step workflows that need reliability,
  autoscaling, and observability.

  If you want Asya to be a standalone agentic environment, the biggest gaps are the agent loop (LLM reasoning cycle) and memory — but adding
  those risks duplicating what frameworks like OpenClaw, LangGraph, or ADK already do well. The higher-leverage move is to be the best backend
  for those frameworks.

✻ Sautéed for 3m 23s

❯ let's explore agentic use-cases for asya - if openclaw is good for personal poer-user agent in your own machine, where agentic asya is going
 to be used? emphasize asya's unique feature - actor model, state in message (plus optional external state via proxy). explore both asya only
use-cases and asya with claw

● Let me ground this in what's already built and what the architecture uniquely enables.

● 2 Explore agents finished (ctrl+o to expand)
   ├─ Explore agentic flow examples · 28 tool uses · 90.5k tokens
   │  ⎿  Done
   └─ Explore state-proxy capabilities · 21 tool uses · 77.4k tokens
      ⎿  Done

● Now I have deep knowledge of both systems. Let me synthesize this into the analysis you're looking for.

  ---
  Agentic Use-Cases for Asya

  The Positioning Question

  ★ Insight ─────────────────────────────────────
  The key differentiator isn't "what patterns can Asya run" (it can run all 17 agentic patterns). It's what properties does the actor mesh give
   those patterns that no in-process framework can. Three properties define Asya's niche:
  1. State-in-message — the envelope is the single source of truth; actors are pure functions of their input
  2. Independent scaling per step — each actor scales on its own queue depth via KEDA
  3. Durable execution — queues survive pod restarts; no work is lost mid-pipeline
  ─────────────────────────────────────────────────

  Part 1: Where Asya Stands Alone (No OpenClaw Needed)

  These are use-cases where the actor model, state-in-message, and queue-based choreography are the right architecture — not just "possible"
  but genuinely better than an in-process agent loop.

  ---
  1. Multi-Tenant AI Pipeline Platform

  Scenario: A platform team serves 50 internal teams, each with their own AI workflows — content moderation, customer support, data enrichment,
   report generation. Teams define flows; the platform runs them.

  Why Asya:
  - Each team's actors are isolated pods with their own resource quotas, secrets, and scaling policies
  - Flows compile to AsyncActor CRDs — platform teams kubectl apply, not write Python
  - Queue-per-actor means one team's spike doesn't starve others
  - State-in-message means no shared database between teams — complete isolation
  - The gateway exposes each flow as an A2A agent or MCP tool — consumers don't know or care about the pipeline internals

  Why NOT an in-process framework: LangGraph/ADK running 50 teams' workflows in one process = shared memory, shared failures, shared scaling.
  One team's 10x traffic spike kills everyone.

  ---
  2. High-Volume Document Processing (Map-Reduce)

  Scenario: Insurance claims processing — 100K PDFs/day, each needs OCR → classification → extraction → validation → human review (if
  ambiguous) → storage.

  Why Asya:
  - Map-reduce fan-out: Split a batch into individual documents, process N in parallel, aggregate
  - Per-step scaling: OCR actors (GPU-heavy) scale to 20 pods; classification actors (CPU-light) stay at 3
  - State-in-message: Each document's envelope carries its full extraction history — no central DB needed for intermediate state
  - State-proxy for artifacts: OCR output (images, PDFs) stored in S3 via state-proxy; downstream actors read via open("/state/ocr/page1.png")
  - Pause/resume: Ambiguous claims route to x-pause → human reviewer sees the envelope in a dashboard → approves/corrects → resumes

  Envelope at step 4 (validation):
  {
    "payload": {
      "document_id": "CLM-2026-88421",
      "ocr_text": "Patient: Jane Doe...",
      "category": "medical_claim",
      "extracted": {"patient": "Jane Doe", "amount": 4250.00, "date": "2026-03-15"},
      "validation": {"confidence": 0.72, "flags": ["amount_unusual"]}
    }
  }

  Each actor enriched the payload monotonically. By the end, the envelope is the audit trail.

  ---
  3. Agentic RAG with Adaptive Retrieval

  Scenario: Enterprise knowledge assistant — answers questions by searching across 5 data sources (Confluence, Jira, Slack, codebase, internal
  wiki), evaluates relevance, iterates if coverage is insufficient.

  Why Asya:
  - Fan-out to retrievers: 5 retriever actors run in parallel (asyncio.gather in flow), each specialized for one source
  - Evaluator loop: Critic actor scores combined results; if gaps detected, refines query and re-fans-out (while loop in flow DSL)
  - State-in-message accumulates context: Each retrieval round appends to payload["retrieved_chunks"] — the generator sees everything
  - State-proxy for embedding cache: Pre-computed embeddings stored in S3; retriever actors load once, serve many queries
  - Independent secrets: Each retriever actor has its own service account / API key — no credential sharing

  @flow
  async def adaptive_rag(p):
      p = await analyze_query(p)
      p["iteration"] = 0
      while p["iteration"] < 3:
          p["iteration"] += 1
          # Fan-out: all retrievers run simultaneously
          p["chunks"] = await asyncio.gather(
              confluence_retriever(p),
              jira_retriever(p),
              slack_retriever(p),
              code_retriever(p),
              wiki_retriever(p),
          )
          p = await relevance_evaluator(p)
          if p["coverage_score"] > 0.85:
              break
          p = await query_refiner(p)
      p = await generator(p)
      p = await fact_checker(p)
      return p

  ---
  4. Multi-Model Evaluation & Selection (Voting/Debate)

  Scenario: Content generation where quality matters more than latency — marketing copy, legal summaries, medical reports. Multiple LLMs
  generate candidates; a judge selects the best.

  Why Asya:
  - Fan-out to different models: GPT-4, Claude, Gemini run as separate actors, each with its own API key and rate limits
  - Actors are model-agnostic: Each actor is just dict → dict — swap the model by changing a ConfigMap, not code
  - Debate pattern: Multi-round refinement where agents see each other's outputs and revise — each round is a fan-out + fan-in cycle
  - State-in-message carries all drafts: The judge actor sees payload["drafts"] with all candidates and their revision history

  Unique property: Because each model call is a separate pod, you can set different resource limits, timeouts, and retry policies per model.
  Claude gets 120s timeout; GPT-4 gets 60s. If one provider is down, its actor retries or routes to DLQ — the others continue.

  ---
  5. Long-Running Agentic Workflows with Checkpoints

  Scenario: Research agent that takes hours — literature review → hypothesis generation → experiment design → (human approval) → execution →
  analysis → report writing.

  Why Asya:
  - Durable queues = free checkpointing: If the cluster restarts mid-pipeline, messages survive in RabbitMQ/SQS. No checkpoint code needed.
  - Pause/resume is native: After "hypothesis generation," route to x-pause — the envelope is checkpointed to S3. A researcher reviews the
  hypothesis days later, adds feedback, and resumes
  - State-proxy for research artifacts: Papers, datasets, intermediate results stored in S3 — actors read/write via
  open("/state/research/papers/...")
  - No timeout pressure: Unlike OpenClaw (48h max), Asya has no inherent timeout — the message sits in a queue indefinitely until consumed

  This is the "overnight agent" pattern: kick off a complex pipeline, go to sleep, find results in the morning — with human gates at critical
  decision points.

  ---
  6. Guardrailed Production AI (Safety Sandwich)

  Scenario: Customer-facing AI that must pass input validation, output filtering, PII detection, and compliance checks — with safe fallbacks on
   failure.

  Why Asya:
  - Try/except in Flow DSL compiles to resiliency policies in the sidecar — safety isn't application code, it's infrastructure
  - Each guardrail is a separate actor: Input validator, PII detector, output filter — each can be maintained, versioned, and scaled
  independently
  - DLQ routing: If the core agent fails, the sidecar routes to x-sump (DLQ) automatically — no unhandled failures reach users
  - Audit trail: The envelope carries the full processing history — compliance team can inspect any request's journey

  @flow
  async def safe_agent(p):
      try:
          p = await input_validator(p)        # blocks prompt injection
          p = await pii_detector(p)           # redacts PII
          p = await core_agent(p)             # LLM reasoning
          p = await output_filter(p)          # blocks data leaks
          p = await compliance_checker(p)     # regulatory compliance
      except:
          p = await safe_fallback(p)          # polite refusal
      return p

  ---
  Part 2: Asya + OpenClaw Hybrid Use-Cases

  ★ Insight ─────────────────────────────────────
  The integration model is: OpenClaw owns the "last mile" (user interaction, memory, local tools, channels) and Asya owns the "pipeline mile"
  (multi-step processing, scaling, durability). OpenClaw is the agent's brain; Asya is its hands and legs in the cloud.
  ─────────────────────────────────────────────────

  ---
  7. Personal Agent with Cloud Backends (OpenClaw → Asya via MCP)

  Scenario: A developer uses OpenClaw as their personal assistant. Most queries are simple (local file ops, web search, memory recall). But
  some require heavy lifting — "analyze all PRs from the last month and write a team performance report."

  Integration:
  - OpenClaw agents see Asya flows as MCP tools (Asya gateway exposes POST /mcp → tools/list)
  - Developer says "analyze team PRs" → OpenClaw's agent loop calls the team-pr-analysis MCP tool → Asya runs: fetch PRs (fan-out per repo) →
  analyze each → aggregate → generate report
  - OpenClaw streams FLY events from Asya via SSE → developer sees progress tokens in real-time
  - Final report lands back in OpenClaw's context → agent summarizes and formats for the developer

  Why hybrid: OpenClaw handles the conversational UX, memory ("last time you asked about PRs, you wanted to focus on code review turnaround"),
  and local context. Asya handles the parallel PR analysis across 20 repos that would take 15 minutes in-process.

  ---
  8. Omni-Channel Agent with Durable Processing (OpenClaw channels → Asya pipelines)

  Scenario: A company wants a customer support agent accessible via WhatsApp, Slack, and web chat. Simple questions are answered instantly;
  complex ones trigger multi-step investigation pipelines.

  Integration:
  - OpenClaw bridges 40+ channels → receives customer message
  - OpenClaw's agent loop handles simple queries (FAQ, memory recall, local tools)
  - For complex queries, OpenClaw dispatches to Asya via A2A (POST /a2a/ with message/send)
  - Asya runs the investigation pipeline: classify → retrieve context → check order status (API call actor) → draft response → quality check
  - Asya streams FLY events back → OpenClaw relays to the customer's channel in real-time
  - If human escalation needed, Asya pauses → support agent reviews in dashboard → resumes → OpenClaw delivers the final answer

  Why hybrid: OpenClaw provides channel diversity (WhatsApp, Slack, Discord) that Asya doesn't have. Asya provides pipeline durability (message
   survives if a pod dies mid-investigation) that OpenClaw can't match with in-process execution.

  ---
  9. Local Agent with Cloud State (Shared State-Proxy)

  Scenario: A research team where each member has a personal OpenClaw agent, but they share a knowledge base of research findings, experiment
  results, and team decisions.

  Integration:
  - State-proxy mounts an S3 bucket as a shared knowledge store
  - Asya actors (running team-wide pipelines) read/write to /state/research/findings/
  - OpenClaw agents access the same S3 bucket via their local filesystem or API
  - When researcher A discovers a finding, their OpenClaw agent saves it → Asya's nightly aggregation pipeline processes all findings →
  generates a team summary → writes back to state-proxy
  - Next morning, researcher B's OpenClaw agent reads the summary from shared state

  Why hybrid: OpenClaw provides personal context (each researcher's preferences, writing style, recent focus). Asya provides the shared
  processing layer (aggregation, cross-referencing, conflict detection via CAS).

  ---
  10. Interactive Agent with Background Processing (Steer + Pipeline)

  Scenario: A data analyst asks their OpenClaw agent to "analyze Q1 sales data and prepare a board presentation." This takes 20 minutes.
  Meanwhile, they keep chatting about other things.

  Integration:
  - OpenClaw dispatches the analysis pipeline to Asya (A2A message/send, non-blocking)
  - Asya runs: data extraction → cleaning → analysis → visualization → slide generation
  - OpenClaw's agent continues handling the analyst's other queries (OpenClaw's queue modes handle this natively)
  - FLY events from Asya stream progress: "Extracted 50K rows...", "Running trend analysis...", "Generating charts..."
  - When done, Asya sends terminal A2A event → OpenClaw notifies the analyst: "Your Q1 presentation is ready"
  - Analyst says "actually, add a section on customer churn" → OpenClaw steers Asya by submitting a new A2A message that resumes the pipeline
  with additional requirements

  Why hybrid: OpenClaw's interactive queue modes (steer/followup/collect) keep the analyst productive. Asya's durable pipeline ensures the
  20-minute analysis survives any interruption.

  ---
  Part 3: The Unique Properties Matrix

  ┌────────────────────────────┬───────────────────────────────────────────────────┬───────────────────────────────────────────────────────┐
  │          Property          │                  What It Enables                  │              In-Process Frameworks Can't              │
  ├────────────────────────────┼───────────────────────────────────────────────────┼───────────────────────────────────────────────────────┤
  │ State-in-message           │ Full audit trail, no shared DB, replay-ability,   │ In-process frameworks use shared session state —      │
  │ (envelope)                 │ actors are pure functions                         │ harder to debug, impossible to replay                 │
  ├────────────────────────────┼───────────────────────────────────────────────────┼───────────────────────────────────────────────────────┤
  │ State-proxy (optional      │ Shared knowledge bases, model weights,            │ In-process frameworks use in-memory state or external │
  │ external state)            │ conversation history — without StatefulSets       │  DBs with tight coupling                              │
  ├────────────────────────────┼───────────────────────────────────────────────────┼───────────────────────────────────────────────────────┤
  │ Queue-per-actor            │ Independent scaling, backpressure, retry per step │ In-process frameworks scale the whole process, not    │
  │                            │                                                   │ individual steps                                      │
  ├────────────────────────────┼───────────────────────────────────────────────────┼───────────────────────────────────────────────────────┤
  │ Durable queues             │ Crash recovery without checkpoint code, overnight │ In-process frameworks lose state on crash unless they │
  │                            │  pipelines                                        │  implement checkpointing (like LangGraph)             │
  ├────────────────────────────┼───────────────────────────────────────────────────┼───────────────────────────────────────────────────────┤
  │ Pause/resume via x-pause   │ Human-in-the-loop with days/weeks of wait time    │ In-process frameworks timeout (OpenClaw: 48h max)     │
  ├────────────────────────────┼───────────────────────────────────────────────────┼───────────────────────────────────────────────────────┤
  │ Flow DSL → CPS compilation │ Declarative pipeline definition, team-owned       │ In-process frameworks require imperative              │
  │                            │ sub-flows                                         │ orchestration code                                    │
  ├────────────────────────────┼───────────────────────────────────────────────────┼───────────────────────────────────────────────────────┤
  │ Actor isolation            │ Different models, secrets, resource limits, and   │ In-process frameworks share process memory,           │
  │                            │ retry policies per step                           │ credentials, and failure domains                      │
  ├────────────────────────────┼───────────────────────────────────────────────────┼───────────────────────────────────────────────────────┤
  │ A2A + MCP gateway          │ Standard protocol interop with any agent          │ Most frameworks use proprietary APIs                  │
  │                            │ framework                                         │                                                       │
  └────────────────────────────┴───────────────────────────────────────────────────┴───────────────────────────────────────────────────────┘

  Bottom Line

  Asya alone is the right choice when you need: multi-tenant isolation, per-step scaling, durable long-running pipelines, high-volume batch
  processing, or production safety guardrails as infrastructure (not application code).

  Asya + OpenClaw is the right choice when you need: personal/interactive UX on top of durable cloud pipelines, multi-channel delivery
  (WhatsApp/Slack/Discord) with reliable backend processing, or shared team state with personal agent context.

  The state-in-message model is Asya's deepest differentiator. It's functional programming applied to distributed AI: actors are pure, the
  envelope is immutable (append-only enrichment), and the pipeline is a composition of transformations. This gives you replay-ability,
  debuggability, and audit trails for free — properties that matter enormously in production agentic systems where you need to answer "why did
  the agent do that?"

✻ Sautéed for 3m 37s

❯ research the code base and define missing functionality (in details - check code and documentation in docs/) - for part 1 and part 2 but
instead of openclaw let's see any agentic tool (claude code, goose, etc - whatever AI running somewhere locally or remotely that's able to
interact with asya deployed in a separate k8s cluster managed by your company's platform team). create
.aint/docs/roadmap/agentic-patterns/<pattern>/{pattern.md,missing.md} or other docs (for now in .aint not in main branch - to save but not
commit. make sure .aint/.gitignore tracks these files docs/roadmap/)

● Let me do a thorough code-level investigation of the gaps. I'll explore multiple areas in parallel.

● 4 Explore agents finished (ctrl+o to expand)
   ├─ Explore gateway A2A/MCP gaps · 45 tool uses · 80.8k tokens
   │  ⎿  Done
   ├─ Explore flow DSL agentic gaps · 31 tool uses · 100.8k tokens
   │  ⎿  Done
   ├─ Explore pause/resume and crew gaps · 52 tool uses · 76.2k tokens
   │  ⎿  Done
   └─ Explore docs and existing roadmap · 26 tool uses · 101.6k tokens
      ⎿  Done

● Excellent research. Now let me create the roadmap documents. First, let me check the .aint structure.

  Read 2 files (ctrl+o to expand)

● Now I'll create the directory structure and all the roadmap documents. Let me start with the gitignore update and directory creation, then
  write all files in parallel.

● Bash(mkdir -p /home/a.yushkovskiy/asya/.aint/docs/roadmap/agentic-patterns/{multi-tenant-platform,document-processing,adaptive-rag,multi-mode
      l-evaluation,long-runnin…)
  ⎿  Done

  Read 1 file (ctrl+o to expand)

● Update(.aint/.gitignore)
  ⎿  Added 2 lines
       8  !aints/**
       9  !scripts/
      10  !scripts/**
      11 +!docs/
      12 +!docs/**

● Now let me write all the documents. I'll create them in parallel batches.

● Write(.aint/docs/roadmap/agentic-patterns/README.md)
  ⎿  Wrote 49 lines to .aint/docs/roadmap/agentic-patterns/README.md
       1 # Agentic Patterns Roadmap
       2
       3 Gap analysis for Asya's agentic use-cases. Each pattern directory contains:
       4 - `pattern.md` — use-case description, architecture, why Asya fits
       5 - `missing.md` — concrete code-level gaps blocking the pattern, with file references
       6
       7 ## Standalone Asya Patterns
       8
       9 These leverage Asya's unique properties (actor model, state-in-message, queue-based
      10 choreography) for use-cases where no external agent framework is needed.
     … +39 lines (ctrl+o to expand)

● Write(.aint/docs/roadmap/agentic-patterns/multi-tenant-platform/pattern.md)
  ⎿  Wrote 55 lines to .aint/docs/roadmap/agentic-patterns/multi-tenant-platform/pattern.md
      1 # Multi-Tenant AI Pipeline Platform
      2
      3 ## Use-Case
      4
      5 A platform team serves N internal teams (content moderation, customer support,
      6 data enrichment, report generation). Teams define flows in Python; the platform
      7 deploys and runs them as AsyncActor CRDs on a shared Kubernetes cluster.
      8
      9 ## Why Asya
     … +45 lines (ctrl+o to expand)

● Write(.aint/docs/roadmap/agentic-patterns/multi-tenant-platform/missing.md)
  ⎿  Wrote 76 lines to .aint/docs/roadmap/agentic-patterns/multi-tenant-platform/missing.md
       1 # Multi-Tenant Platform: Missing Functionality
       2
       3 ## P0 — Blocking
       4
       5 ### 1. No per-namespace flow isolation in gateway
       6
       7 **Current state**: Gateway serves all flows from a single ConfigMap directory.
       8 All MCP tools and A2A skills are visible to all authenticated clients.
       9
      10 **Files**:
     … +66 lines (ctrl+o to expand)

● Write(.aint/docs/roadmap/agentic-patterns/document-processing/pattern.md)
  ⎿  Wrote 79 lines to .aint/docs/roadmap/agentic-patterns/document-processing/pattern.md
       1 # High-Volume Document Processing (Map-Reduce)
       2
       3 ## Use-Case
       4
       5 Batch processing of documents at scale — insurance claims (100K PDFs/day),
       6 legal contract analysis, invoice extraction, medical record summarization.
       7 Each document flows through: ingestion, OCR/parsing, classification,
       8 extraction, validation, optional human review, storage.
       9
      10 ## Why Asya
     … +69 lines (ctrl+o to expand)

● Write(.aint/docs/roadmap/agentic-patterns/document-processing/missing.md)
  ⎿  Wrote 94 lines to .aint/docs/roadmap/agentic-patterns/document-processing/missing.md
       1 # Document Processing: Missing Functionality
       2
       3 ## P0 — Blocking
       4
       5 ### 1. Fan-in has no timeout
       6
       7 **Current state**: Fan-in aggregator waits for all N slices. If one branch
       8 hangs (OCR on a corrupted PDF), the entire batch blocks indefinitely.
       9
      10 **Files**:
     … +84 lines (ctrl+o to expand)

● Write(.aint/docs/roadmap/agentic-patterns/adaptive-rag/pattern.md)
  ⎿  Wrote 75 lines to .aint/docs/roadmap/agentic-patterns/adaptive-rag/pattern.md
       1 # Adaptive RAG with Iterative Retrieval
       2
       3 ## Use-Case
       4
       5 Enterprise knowledge assistant that answers questions by searching across
       6 multiple data sources (Confluence, Jira, Slack, codebase, internal wiki).
       7 Evaluates relevance after each retrieval round and iterates if coverage
       8 is insufficient — unlike simple RAG which retrieves once and generates.
       9
      10 ## Why Asya
     … +65 lines (ctrl+o to expand)

● Write(.aint/docs/roadmap/agentic-patterns/adaptive-rag/missing.md)
  ⎿  Wrote 84 lines to .aint/docs/roadmap/agentic-patterns/adaptive-rag/missing.md
      1 # Adaptive RAG: Missing Functionality
      2
      3 ## P0 — Blocking
      4
      5 ### 1. Max-iteration guard not enforced
      6
      7 **Current state**: `FlowCompiler(max_iterations=100)` stores the limit but
      8 never checks it. Generated loop-back routers have no iteration counter or
      9 guard. An evaluator that always returns `coverage < 0.85` loops forever.
     … +74 lines (ctrl+o to expand)

● Write(.aint/docs/roadmap/agentic-patterns/multi-model-evaluation/pattern.md)
  ⎿  Wrote 98 lines to .aint/docs/roadmap/agentic-patterns/multi-model-evaluation/pattern.md
       1 # Multi-Model Evaluation & Selection (Voting/Debate)
       2
       3 ## Use-Case
       4
       5 Content generation where quality matters more than latency — marketing copy,
       6 legal summaries, medical reports, code reviews. Multiple LLMs generate
       7 candidates in parallel; a judge selects the best. Optionally, multi-round
       8 debate where agents see each other's outputs and refine.
       9
      10 ## Why Asya
     … +88 lines (ctrl+o to expand)

● Write(.aint/docs/roadmap/agentic-patterns/multi-model-evaluation/missing.md)
  ⎿  Wrote 75 lines to .aint/docs/roadmap/agentic-patterns/multi-model-evaluation/missing.md
       1 # Multi-Model Evaluation: Missing Functionality
       2
       3 ## P0 — Blocking
       4
       5 ### 1. Fan-in partial failure (same as document-processing)
       6
       7 If one model provider is down, its actor fails. Fan-in has no policy for
       8 proceeding with N-1 results. The judge needs at least 2 candidates to compare.
       9
      10 **What's needed**: Configurable `min_results` on fan-in — proceed when
     … +65 lines (ctrl+o to expand)

● Write(.aint/docs/roadmap/agentic-patterns/long-running-checkpointed/pattern.md)
  ⎿  Wrote 84 lines to .aint/docs/roadmap/agentic-patterns/long-running-checkpointed/pattern.md
       1 # Long-Running Agentic Workflows with Checkpoints
       2
       3 ## Use-Case
       4
       5 Research agent that takes hours or days — literature review, hypothesis
       6 generation, experiment design, (human approval), execution, analysis,
       7 report writing. Or: multi-day onboarding pipeline, compliance audit,
       8 due diligence investigation.
       9
      10 The "overnight agent" pattern: kick off a complex pipeline, go to sleep,
     … +74 lines (ctrl+o to expand)

● Write(.aint/docs/roadmap/agentic-patterns/long-running-checkpointed/missing.md)
  ⎿  Wrote 103 lines to .aint/docs/roadmap/agentic-patterns/long-running-checkpointed/missing.md
      1 # Long-Running Checkpointed: Missing Functionality
      2
      3 ## P0 — Blocking
      4
      5 ### 1. Pause metadata not exposed via A2A GetTask
      6
      7 **Current state**: `x-pause` stores pause metadata (prompt text, required
      8 fields with types) in the checkpoint. Gateway receives it via sidecar
      9 progress report. But `GetTask()` does NOT return this metadata to clients.
     … +93 lines (ctrl+o to expand)

● Write(.aint/docs/roadmap/agentic-patterns/guardrailed-production/pattern.md)
  ⎿  Wrote 73 lines to .aint/docs/roadmap/agentic-patterns/guardrailed-production/pattern.md
       1 # Guardrailed Production AI (Safety Sandwich)
       2
       3 ## Use-Case
       4
       5 Customer-facing AI that must pass input validation, output filtering, PII
       6 detection, and compliance checks — with safe fallbacks on failure. Used in
       7 regulated industries (healthcare, finance, legal) where AI output must meet
       8 compliance standards before reaching users.
       9
      10 ## Why Asya
     … +63 lines (ctrl+o to expand)

● Write(.aint/docs/roadmap/agentic-patterns/guardrailed-production/missing.md)
  ⎿  Wrote 94 lines to .aint/docs/roadmap/agentic-patterns/guardrailed-production/missing.md
      1 # Guardrailed Production: Missing Functionality
      2
      3 ## P0 — Blocking
      4
      5 ### 1. Exception type matching is name-only
      6
      7 **Current state**: Parser extracts exception type names as strings
      8 (`['ValueError', 'ConnectionError']`) but doesn't validate that actors can
      9 raise these types or link them to sidecar resiliency policies.
     … +84 lines (ctrl+o to expand)

● Now the external agent integration patterns:

● Write(.aint/docs/roadmap/agentic-patterns/agent-mcp-backend/pattern.md)
  ⎿  Wrote 80 lines to .aint/docs/roadmap/agentic-patterns/agent-mcp-backend/pattern.md
      1 # Agent MCP Backend (External Agent -> Asya via MCP)
      2
      3 ## Use-Case
      4
      5 A developer uses an agentic coding tool (Claude Code, Goose, Aider, Cursor,
      6 Windsurf) or a custom MCP client. Most tasks are local (file edits, shell
      7 commands, web search). But some require heavy cloud processing — "analyze all
      8 PRs from last month", "run security audit across 20 repos", "generate API
      9 documentation from OpenAPI specs across all microservices."
     … +70 lines (ctrl+o to expand)

● Write(.aint/docs/roadmap/agentic-patterns/agent-mcp-backend/missing.md)
  ⎿  Wrote 123 lines to .aint/docs/roadmap/agentic-patterns/agent-mcp-backend/missing.md
      1 # Agent MCP Backend: Missing Functionality
      2
      3 ## P0 — Blocking
      4
      5 ### 1. No input/output schema extraction from Flow DSL
      6
      7 **Current state**: MCP tool schemas must be manually written in gateway
      8 ConfigMap YAML. The flow compiler doesn't extract schemas from flow
      9 function signatures or docstrings.
     … +113 lines (ctrl+o to expand)

● Write(.aint/docs/roadmap/agentic-patterns/agent-a2a-integration/pattern.md)
  ⎿  Wrote 84 lines to .aint/docs/roadmap/agentic-patterns/agent-a2a-integration/pattern.md
       1 # Agent A2A Integration (External Agent <-> Asya via A2A)
       2
       3 ## Use-Case
       4
       5 An organization runs multiple AI agent systems — some local (Claude Code on
       6 developer laptops), some cloud (Google ADK agents, LangGraph services,
       7 custom orchestrators). These agents need to collaborate on complex tasks by
       8 delegating sub-tasks to each other via the A2A (Agent-to-Agent) protocol.
       9
      10 Asya acts as an A2A server: external agents discover Asya's capabilities via
     … +74 lines (ctrl+o to expand)

● Write(.aint/docs/roadmap/agentic-patterns/agent-a2a-integration/missing.md)
  ⎿  Wrote 124 lines to .aint/docs/roadmap/agentic-patterns/agent-a2a-integration/missing.md
       1 # Agent A2A Integration: Missing Functionality
       2
       3 ## P0 — Blocking
       4
       5 ### 1. Pause metadata not returned in A2A GetTask or status events
       6
       7 **Current state**: When a task pauses, the A2A status transitions to
       8 `input_required`. But the pause metadata (prompt text, required fields with
       9 types, validation rules) is NOT included in the status event or GetTask
      10 response. External agents see "input required" but don't know WHAT input.
     … +114 lines (ctrl+o to expand)

● Write(.aint/docs/roadmap/agentic-patterns/shared-state-collaboration/pattern.md)
  ⎿  Wrote 86 lines to .aint/docs/roadmap/agentic-patterns/shared-state-collaboration/pattern.md
       1 # Shared State Collaboration (Agent + Asya via State-Proxy)
       2
       3 ## Use-Case
       4
       5 A team of developers or researchers, each with their own local AI agent
       6 (Claude Code, Goose, etc.), shares a knowledge base of findings, experiment
       7 results, and decisions. Asya pipelines process team-wide aggregation tasks;
       8 local agents read/write shared state.
       9
      10 Also: an external agent runs a long pipeline on Asya and needs to inspect
     … +76 lines (ctrl+o to expand)

● Write(.aint/docs/roadmap/agentic-patterns/shared-state-collaboration/missing.md)
  ⎿  Wrote 107 lines to .aint/docs/roadmap/agentic-patterns/shared-state-collaboration/missing.md
      1 # Shared State Collaboration: Missing Functionality
      2
      3 ## P0 — Blocking
      4
      5 ### 1. No state change notifications (watch/subscribe)
      6
      7 **Current state**: State-proxy is pull-only. If actor A writes a file, actor B
      8 must poll to discover the change. No pub/sub, no filesystem watches, no
      9 event stream for state mutations.
     … +97 lines (ctrl+o to expand)

● Write(.aint/docs/roadmap/agentic-patterns/async-background-processing/pattern.md)
  ⎿  Wrote 97 lines to .aint/docs/roadmap/agentic-patterns/async-background-processing/pattern.md
      1 # Async Background Processing (Agent + Asya Fire-and-Follow)
      2
      3 ## Use-Case
      4
      5 A developer or AI agent dispatches a long-running task to Asya and continues
      6 working on other things. The pipeline runs in the background on the company's
      7 Kubernetes cluster. The agent receives progress updates via streaming and
      8 gets notified when the task completes. Optionally, the agent can steer the
      9 pipeline by sending additional context mid-execution (via pause/resume).
     … +87 lines (ctrl+o to expand)

● Write(.aint/docs/roadmap/agentic-patterns/async-background-processing/missing.md)
  ⎿  Wrote 115 lines to .aint/docs/roadmap/agentic-patterns/async-background-processing/missing.md
       1 # Async Background Processing: Missing Functionality
       2
       3 ## P0 — Blocking
       4
       5 ### 1. No blocking mode for MCP tools/call
       6
       7 **Current state**: MCP `tools/call` dispatches to queue and returns task
       8 metadata immediately. MCP clients (Claude Code, Goose) expect synchronous
       9 tool results. They have no built-in mechanism to poll or subscribe to a
      10 separate stream endpoint.
     … +105 lines (ctrl+o to expand)

● Now let me sync the .aint changes and verify the structure:

● Bash(cd /home/a.yushkovskiy/asya/.aint && find docs/ -type f | sort)
  ⎿  docs/roadmap/agentic-patterns/README.md
     docs/roadmap/agentic-patterns/adaptive-rag/missing.md
     docs/roadmap/agentic-patterns/adaptive-rag/pattern.md
     … +18 lines (ctrl+o to expand)

● Bash(cd /home/a.yushkovskiy/asya/.aint && git status --short)
  ⎿   M .gitignore
     ?? docs/

● Good — .gitignore is modified and docs/ is untracked (will be added). Let me commit and push to aint-sync:

● Bash(git add .gitignore docs/ && git commit -m "$(cat <<'EOF'
      Add agentic patterns roadmap with gap analysis…)
  ⎿  Error: Exit code 1
     No .pre-commit-config.yaml file was found
     - To temporarily silence this, run `PRE_COMMIT_ALLOW_NO_CONFIG=1 git ...`
     - To permanently silence this, install pre-commit with the --allow-missing-config option
     - To uninstall pre-commit run `pre-commit uninstall`

● Bash(PRE_COMMIT_ALLOW_NO_CONFIG=1 git add .gitignore docs/ && PRE_COMMIT_ALLOW_NO_CONFIG=1 git commit -m "$(cat <<'EOF'
      Add agentic patterns roadmap with gap analysi…)
  ⎿  `.pre-commit-config.yaml` config file not found. Skipping `pre-commit`.
     [aint-sync 5e79ed5d] Add agentic patterns roadmap with gap analysis
      22 files changed, 1857 insertions(+)
     … +18 lines (ctrl+o to expand)

● Bash(git pull --rebase && git push)
  ⎿  Current branch aint-sync is up to date.
     To github.com-agent:deliveryhero/asya.git
        55e80271..5e79ed5d  aint-sync -> aint-sync

● All committed and pushed to aint-sync. Here's the summary:

  ---
  Created: 10 Agentic Pattern Roadmap Documents

  ★ Insight ─────────────────────────────────────
  The gap analysis is grounded in actual code exploration — every "missing" item references specific source files, function names, and line
  numbers. This makes the roadmap actionable: each gap can become an aint with clear implementation scope.
  ─────────────────────────────────────────────────

  Structure

  .aint/docs/roadmap/agentic-patterns/
  ├── README.md                          (index + cross-cutting gaps)
  ├── multi-tenant-platform/             { pattern.md, missing.md }
  ├── document-processing/               { pattern.md, missing.md }
  ├── adaptive-rag/                      { pattern.md, missing.md }
  ├── multi-model-evaluation/            { pattern.md, missing.md }
  ├── long-running-checkpointed/         { pattern.md, missing.md }
  ├── guardrailed-production/            { pattern.md, missing.md }
  ├── agent-mcp-backend/                 { pattern.md, missing.md }
  ├── agent-a2a-integration/             { pattern.md, missing.md }
  ├── shared-state-collaboration/        { pattern.md, missing.md }
  └── async-background-processing/       { pattern.md, missing.md }

  Top P0 Gaps (Blocking Multiple Patterns)

  ┌──────────────────────────────────────────────────────────────────────┬────────────────────────────────────────────┬───────────────────┐
  │                                 Gap                                  │                  Affects                   │     Component     │
  ├──────────────────────────────────────────────────────────────────────┼────────────────────────────────────────────┼───────────────────┤
  │ MCP blocking tools/call — agents expect sync results                 │ agent-mcp-backend, async-background        │ Gateway MCP       │
  │                                                                      │                                            │ handlers          │
  ├──────────────────────────────────────────────────────────────────────┼────────────────────────────────────────────┼───────────────────┤
  │ Fan-in timeout + partial failure — one hanging branch blocks all     │ document-processing, adaptive-rag,         │ Sidecar + codegen │
  │                                                                      │ multi-model                                │                   │
  ├──────────────────────────────────────────────────────────────────────┼────────────────────────────────────────────┼───────────────────┤
  │ Max-iteration guard not enforced — compiler stores limit, never      │ adaptive-rag, multi-model debate           │ Flow compiler     │
  │ checks                                                               │                                            │                   │
  ├──────────────────────────────────────────────────────────────────────┼────────────────────────────────────────────┼───────────────────┤
  │ Pause metadata not in GetTask/A2A events — agents can't know what    │ long-running, a2a-integration,             │ Gateway A2A       │
  │ input is needed                                                      │ async-background                           │ executor          │
  ├──────────────────────────────────────────────────────────────────────┼────────────────────────────────────────────┼───────────────────┤
  │ No input/output schema from Flow DSL — MCP tool registration         │ agent-mcp-backend, multi-tenant            │ Flow compiler     │
  │ requires manual YAML                                                 │                                            │                   │
  ├──────────────────────────────────────────────────────────────────────┼────────────────────────────────────────────┼───────────────────┤
  │ Exception type routing is catch-all only — no typed except handlers  │ guardrailed-production                     │ Parser + sidecar  │
  └──────────────────────────────────────────────────────────────────────┴────────────────────────────────────────────┴───────────────────┘

  What's Already Solid

  The analysis also confirmed what's working well:
  - Pause/resume full cycle (x-pause -> S3 checkpoint -> x-resume with input merge)
  - Sidecar resiliency (retry with backoff, DLQ routing, SLA enforcement)
  - A2A protocol core (message/send, task cancel, streaming artifacts, Agent Card)
  - FLY event streaming (cross-process via PG NOTIFY, SSE to external clients)
  - State-proxy with CAS conflict detection (S3, GCS, Redis backends)
  - Flow DSL compilation (while loops, fan-out/fan-in, try/except, sub-flows)

✻ Worked for 10m 56s
