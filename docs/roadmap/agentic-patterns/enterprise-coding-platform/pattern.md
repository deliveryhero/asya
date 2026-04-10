# Agentic Workbench Platform

## The Problem

Today, data scientists and ML engineers who need to run research or agentic coding
at scale face a painful choice:

- **JupyterLab**: Heavy, static, one notebook per user, can't scale horizontally.
  If you need 10 parallel research agents, you're out of luck. If the server dies,
  your running experiment dies with it.
- **Local machine**: Limited by laptop resources, no GPU, can't leave overnight tasks
  running when you close your laptop.
- **Ad-hoc VMs**: SSH into a cloud VM, but no lifecycle management, no shared data,
  no way to fan out work to parallel workers.

## The Vision

Replace heavy static workbenches with a **two-tier model**:

1. **Workbench pod** (Tier 1): A regular long-running pod the researcher SSHes into
   (VS Code Remote, terminal). Has FUSE/state-proxy mounts to S3 with pre-downloaded
   datasets. The researcher experiments interactively here — this is their "desk."

2. **Research agent actors** (Tier 2): Ephemeral Asya actors that the researcher
   spawns for heavy/parallel work. Think Karpathy's autoresearch — 10 agents each
   searching the web, analyzing papers, running experiments. They share the same
   S3 data (read-only or append-only), do a chunk of work, write results, and die.
   A heartbeat message (from the workbench or a cron job) wakes them up for the
   next chunk.

The agents are NOT long-running pods. They follow the **interrupt-driven** pattern:
wake on message, read state from S3, do work, write results to S3, die. If a pod
crashes, the heartbeat retries. If you need more parallelism, more heartbeats spawn
more pods via KEDA.

## Why Asya

This model maps directly to Asya's architecture:

| Concept | Asya Primitive |
|---|---|
| Research agent | AsyncActor (queue-driven, ephemeral pod) |
| Shared datasets | State-proxy mount (S3/GCS, read-only) |
| Research results | State-proxy mount (S3/GCS, append with CAS) |
| Spawn 10 agents | Fan-out (10 messages, KEDA scales to 10 pods) |
| Heartbeat | Cron-triggered message to actor queue |
| Progress streaming | FLY events (SSE to workbench or gateway) |
| Coordination | MQ — actors route envelopes to each other |
| Crash recovery | Queue retry — message not ACKed, redelivered |

## Architecture

```
Researcher (SSH / VS Code Remote)
+-------------------------------------------+
| Workbench Pod (long-running, NOT an actor) |
|                                           |
|  /data/datasets  ── FUSE mount ──> S3 (read-only, pre-downloaded)
|  /data/results   ── FUSE mount ──> S3 (append, shared with agents)
|  /workspace      ── PVC or git clone                              
|                                           |
|  The researcher:                          |
|    - Explores data interactively          |
|    - Develops agent code                  |
|    - Dispatches research tasks via MQ     |
|    - Monitors results in /data/results/   |
+-----+-------------------------------------+
      |
      | Sends task messages to actor queues
      | (or cron job sends heartbeats)
      |
+-----v----------------------------------------+
| Transport (NATS JetStream / RabbitMQ / SQS)  |
|   research-agent.task-1                       |
|   research-agent.task-2                       |
|   ...                                        |
|   research-agent.task-N                       |
+---+--------+--------+---------+--------------+
    |        |        |         |
+---v---+ +--v----+ +-v-----+ +v------+
| Agent | | Agent | | Agent | | Agent |  (KEDA: 0 → N)
| Pod 1 | | Pod 2 | | Pod 3 | | Pod N |
|       | |       | |       | |       |
| state-proxy:                        |
|   /data (S3 read-only)              |
|   /results (S3 append, CAS)         |
|   /checkpoint (S3 read-write)       |
|                                     |
| Each invocation:                    |
|   1. Read checkpoint (where I left off)
|   2. Read task from payload         |
|   3. Do work (web search, LLM, compute)
|   4. Write results to /results/     |
|   5. Write checkpoint (progress)    |
|   6. Die (message ACKed)            |
+-------------------------------------+
```

## The Heartbeat Pattern

Instead of long-running pods that accumulate memory leaks and stale connections:

```
Cron Job (every 5 min)
  └── Publishes heartbeat message to each agent's queue
        └── KEDA detects queue depth > 0
              └── Scales pod from 0 → 1
                    └── Pod starts, reads checkpoint from S3
                          └── Picks next work item from task list
                                └── Does work (search, analyze, generate)
                                      └── Writes results + checkpoint to S3
                                            └── Pod dies (queue empty)
                                                  └── KEDA scales to 0

Next heartbeat: repeat from checkpoint
```

This simulates OpenClaw's "session lanes" but distributed:
- Each agent has its own queue (= OpenClaw session lane)
- Heartbeat = OpenClaw's "followup" queue mode
- Checkpoint = OpenClaw's workspace memory
- Pod death + restart = clean slate, no state corruption

## Coordination Between Agents

Research agents sharing S3 need to avoid duplicating work. Three patterns:

### (a) Task List in S3 (simplest)
```python
# Orchestrator writes task list
with open("/results/tasks.json", "w") as f:
    json.dump([
        {"id": "t1", "query": "transformers survey 2026", "status": "pending"},
        {"id": "t2", "query": "RLHF alternatives", "status": "pending"},
    ], f)

# Agent claims a task (CAS prevents double-claim)
tasks = json.load(open("/results/tasks.json"))
my_task = next(t for t in tasks if t["status"] == "pending")
my_task["status"] = "claimed"
my_task["agent"] = os.getenv("POD_NAME")
# CAS write — if another agent claimed between read and write, FileExistsError
```

### (b) Per-Agent Queues (Asya-native)
Fan-out: orchestrator sends one message per task, each to its own queue.
No coordination needed — each agent gets exactly one task per heartbeat.

### (c) Envelope Routing (actors talk to each other)
Agent A discovers something relevant to Agent B's research topic.
Agent A yields an envelope routed to Agent B's queue:
```python
yield "SET", ".route.next", ["agent-b"]
yield {"finding": "...", "from_agent": "agent-a"}
```

## Example: Autoresearch Pipeline

```python
# Researcher dispatches from workbench:
for topic in ["RLHF alternatives", "scaling laws 2026", "emergent abilities"]:
    publish_to_queue("research-agent", {
        "task": "deep_search",
        "topic": topic,
        "max_iterations": 5,
        "output_dir": f"/results/research/{slugify(topic)}/"
    })

# Each agent runs independently, writing to its output_dir:
# /results/research/rlhf-alternatives/
#   ├── iteration-1.json    (search results)
#   ├── iteration-2.json    (refined search)
#   ├── iteration-3.json    (analysis)
#   ├── summary.json        (final findings)
#   └── checkpoint.json     (resume state)

# After all agents complete, researcher reads results:
# ls /data/results/research/
# rlhf-alternatives/  scaling-laws-2026/  emergent-abilities/
```

## Example: GPU-Bound Experiment

```python
# Researcher designs experiment on workbench, then dispatches:
for config in hyperparameter_grid:
    publish_to_queue("gpu-experiment", {
        "task": "train_model",
        "config": config,
        "dataset": "/data/datasets/imagenet-subset/",
        "output_dir": f"/results/experiments/{config['name']}/"
    })

# GPU actors (KEDA scales based on queue depth + GPU availability):
# - Read dataset from shared S3 (read-only mount)
# - Train model with given hyperparameters
# - Write metrics + model checkpoint to /results/experiments/
# - Die after training completes
```

## Enterprise Platform Layer

For a DevX team providing this company-wide:

- **Project templates**: Pre-built workbench images per team (DS, ML, SWE) with
  standard toolchains and pre-downloaded datasets
- **GPU scheduling**: KEDA + node selectors for GPU actors (A100, H100 pools)
- **Cost attribution**: Per-user compute + GPU hours tracked via sidecar metrics
- **Data governance**: Read-only S3 mounts prevent agents from modifying source
  datasets. Results written to team-scoped prefixes.
- **Shared results**: Team members see each other's research results via shared
  S3 prefix. State-proxy CAS prevents corruption.
