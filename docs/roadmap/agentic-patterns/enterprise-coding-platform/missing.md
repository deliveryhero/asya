# Agentic Workbench Platform: Missing Functionality

The revised model (workbench + heartbeat-driven agents) has fewer gaps than the
previous "coding agent as a service" model because it plays to Asya's strengths.
The agents ARE Asya actors — ephemeral, queue-driven, state-in-files.

---

## Layer 1: State-Proxy / Data Access

### P0-SP-1. No FUSE mount — only Python builtins patched

**This is the single biggest gap for this use-case.**

**Current state**: State-proxy patches `builtins.open()`, `os.stat()`,
`os.listdir()`, etc. This works for pure-Python code but NOT for:
- C-extension libraries (pandas `pd.read_csv()`, PyTorch `torch.load()`,
  numpy `np.load()`, OpenCV `cv2.imread()`)
- Shell commands (`cat`, `grep`, `wc`, `head`)
- Git operations (`git clone`, `git log`)
- Any non-Python tool in the container

For a research workbench where data scientists use pandas, PyTorch, and shell
tools on S3-backed data, Python-only patching is a non-starter.

**Files**:
- `src/asya-runtime/asya_runtime.py:983-1155` — `_install_state_proxy_hooks()`
  patches only Python builtins
- No FUSE code anywhere in the codebase (confirmed by search)

**What's needed**: FUSE-based state-proxy mount.

**Options**:
- **(a) goofys / s3fs-fuse**: Off-the-shelf FUSE mount for S3. NOT Asya-specific.
  Deploy as sidecar or init container. Zero Asya code needed. Works for
  workbench pods AND actor pods.
  - Pro: Zero development effort
  - Con: No CAS, no xattr integration, no Asya-native metrics
  - Con: Latency on metadata operations (ls, stat) can be slow

- **(b) Custom FUSE connector**: Replace the HTTP-over-Unix-socket with a FUSE
  mount backed by the same connector sidecars. The connector sidecar serves
  FUSE instead of HTTP.
  - Pro: Full CAS support, xattr, Asya metrics
  - Pro: Same connector images work for both FUSE and Python-patched modes
  - Con: Significant engineering (~4-6 weeks), requires privileged containers
    or `--device /dev/fuse`

- **(c) Hybrid**: Use goofys/s3fs for workbench pods (no Asya dependency),
  keep Python-patched state-proxy for actor pods (where handlers are Python).
  This is the pragmatic path — workbench doesn't need CAS or xattr.

**Recommendation**: Start with (c). Workbench pods use s3fs-fuse for
transparent filesystem access. Actor pods continue using state-proxy with
Python patching (handlers are Python, `io.BytesIO` workaround for C libs).
Add FUSE connector (b) as a later enhancement.

### P0-SP-2. No read-only mount mode

**Current state**: State-proxy has no mount-level read-only flag. Any pod that
mounts a state-proxy path can write to it. For shared datasets, you want
multiple pods to read but NOT write.

**Files**:
- `deploy/helm-charts/asya-crossplane/templates/xrd-asyncactor.yaml:340-346`
  — `writeMode` only has `buffered` and `passthrough`, no `readonly`
- `src/asya-runtime/asya_runtime.py` — no read-only check on mount config

**What's needed**:
- `writeMode: readonly` in AsyncActor CRD
- Runtime refuses `open(..., "w")` on read-only mounts (raises `PermissionError`)
- For FUSE/s3fs: mount with `-o ro` flag

**Effort**: Small (1-2 days for runtime + CRD change).

### P1-SP-3. No append-only mode (create-new-files-only)

**Current state**: CAS prevents overwriting keys that changed since last read,
but doesn't prevent overwriting keys at all. For research results where
multiple agents write to the same prefix, you want "create new files but never
overwrite existing ones."

**What's needed**:
- `writeMode: append` — all writes use `exclusive=True` (If-None-Match: *)
- Agents write to unique keys: `/results/agent-1/finding-001.json`
- Any attempt to overwrite existing key raises `FileExistsError`

**Effort**: Small (2-3 days). The exclusive flag already exists in the runtime;
just need a mount-level default.

---

## Layer 2: Heartbeat / Trigger Mechanism

### P0-HB-1. No cron/heartbeat message trigger

**Current state**: Actors consume messages placed by upstream actors or the
gateway. No built-in mechanism to send periodic "wake up" messages. The
existing aint (`open.1f7m`) is scoped to retry-delay, not heartbeat.

**Files**:
- `.aint/aints/agentic-umbrella/open.1f7m.scheduled-trigger-crew-actors-cronjob-based-delay-transports.md`
  — low priority, narrowly scoped

**What's needed** (two options):

**(a) External CronJob** (simplest, no Asya changes):
- Kubernetes CronJob publishes heartbeat messages to actor queues
- CronJob pod has MQ client (NATS, RabbitMQ CLI, AWS CLI for SQS)
- Template provided via `asya-crew` Helm chart
- Payload includes: `{"type": "heartbeat", "timestamp": "...", "agent_id": "..."}`

**(b) Crew actor `x-cron`** (Asya-native):
- New crew actor that runs as a CronJob
- Configurable: target queues, schedule, payload template
- Integrated with AsyncActor CRD: `trigger: { cron: "*/5 * * * *" }`
- When fired, publishes message to actor's input queue

**Recommendation**: Start with (a). A CronJob manifest is trivial to write
and doesn't require Asya code changes. Promote to (b) when multiple teams
need the same pattern.

### P1-HB-2. No "work remaining" check before heartbeat

**Current state** (with external CronJob): Heartbeat fires every 5 minutes
regardless of whether there's work to do. If the agent has no pending tasks
in its task list (in S3), the pod starts, reads the empty list, and dies
immediately. Wasted cold start.

**What's needed**:
- CronJob checks "is there pending work?" before publishing heartbeat
- Options: (a) CronJob reads task list from S3 directly, (b) separate
  "scheduler" actor that maintains task state and only fires heartbeats
  when tasks are pending

---

## Layer 3: Workspace / Workbench Pod

### P1-WB-1. No workbench pod CRD or Helm chart

**Current state**: Asya provides AsyncActor CRD for actor pods. No equivalent
for the researcher's workbench pod (long-running, SSH-enabled, interactive).

**What's needed**:
- Helm chart or CRD for workbench pods with:
  - SSH access (or VS Code Remote tunnel)
  - FUSE/s3fs mounts to shared datasets
  - MQ client pre-installed (for dispatching tasks to actors)
  - GPU support (optional, for interactive experiments)
  - PVC for persistent workspace (/home, project files)

**Alternative**: This is arguably NOT Asya's responsibility. Use a standard
Kubernetes StatefulSet or JupyterHub spawner. The workbench doesn't need
Asya's sidecar or routing. It just publishes messages to actor queues.

**Recommendation**: Provide a documented template (not a CRD). The workbench
is a standard K8s workload that happens to interact with Asya actors via MQ.

### P1-WB-2. No init containers in AsyncActor CRD

**Current state**: AsyncActor composition templates don't render init containers.
Can't run `git clone` or `pip install` before the handler starts.

**Files**:
- `deploy/helm-charts/asya-crossplane/templates/composition-sqs.yaml` — no
  `initContainers` section in pod spec

**What's needed**:
- `initContainers` field in AsyncActor CRD spec
- Composition template renders init containers before runtime + sidecar
- Use cases: git clone workspace, download model weights, install dependencies

**Workaround**: Use class handler `__init__()` to fetch data after runtime
starts. Or bake everything into the container image at build time.

**Effort**: Medium (1-2 weeks for CRD + composition changes).

---

## Layer 4: Agent Coordination

### P1-AC-1. No in-handler message dispatch (yield DISPATCH)

**Current state**: An actor handler can only route its output envelope to the
next actor in `route.next`. It can't dispatch a NEW message to an arbitrary
queue mid-execution (needed for agent-to-agent coordination).

**What's needed** (ABI extension):
```python
# Fire-and-forget: send message to another agent
yield "DISPATCH", {"queue": "agent-b", "payload": {"finding": "..."}}

# Or: dispatch and wait for response (synchronous fan-out within handler)
result = yield "DISPATCH_WAIT", {"queue": "agent-b", "payload": {...}}
```

**Alternative**: Handler publishes directly to NATS/RabbitMQ using a client
library in the container. This bypasses the ABI but works today. Less
observable (no envelope metadata, no tracing).

### P1-AC-2. No shared checkpoint coordination

**Current state**: Each agent reads/writes its own checkpoint in S3. No
mechanism for a "coordinator" to know when all agents have completed their
current iteration (needed for synchronized multi-agent research rounds).

**What's needed**:
- Fan-out/fan-in: orchestrator dispatches N tasks, fan-in aggregator waits
  for all N to complete. This IS the flow DSL pattern, but triggered by
  heartbeat rather than a flow.
- Or: state-proxy based coordination — agents write completion markers,
  coordinator polls for N markers before advancing to next phase.

---

## Layer 5: Enterprise Platform

### P1-EP-1. GPU scheduling integration

**Current state**: AsyncActor CRD supports `nodeSelector` and `tolerations`
but no GPU-aware scheduling primitives (request N GPUs, GPU type selection).

**What's needed**:
- `resources.limits.nvidia.com/gpu: 1` support in actor spec
- Node selector for GPU pools: `gpu-type: a100`
- KEDA scaling aware of GPU availability (don't scale to 10 if only 4 GPUs)

**Effort**: Small — mostly CRD field additions. KEDA GPU-aware scaling is
harder and may require custom scaler.

### P2-EP-2. Cost attribution for GPU workloads

**What's needed**:
- Sidecar metrics with GPU time labels
- Per-user GPU hour tracking
- Integration with cloud billing (GKE, EKS GPU node pools)

---

## Priority Summary

| ID | Gap | Layer | Priority | Effort | Notes |
|---|---|---|---|---|---|
| SP-1 | FUSE mount | State-proxy | P0 | 0 (s3fs) / 4-6w (custom) | Use s3fs-fuse for now |
| SP-2 | Read-only mount mode | State-proxy | P0 | 1-2 days | Add `readonly` writeMode |
| HB-1 | Heartbeat trigger | Trigger | P0 | 1-2 days (CronJob template) | External CronJob first |
| SP-3 | Append-only mode | State-proxy | P1 | 2-3 days | Default `exclusive=True` |
| WB-1 | Workbench template | Workspace | P1 | 1 week | Documented template, not CRD |
| WB-2 | Init containers | Actor | P1 | 1-2 weeks | CRD + composition change |
| AC-1 | In-handler dispatch | ABI | P1 | 2-3 weeks | New ABI verb |
| AC-2 | Checkpoint coordination | Coordination | P1 | 2-3 weeks | Fan-in or state markers |
| HB-2 | Work-remaining check | Trigger | P1 | 1 week | CronJob pre-check |
| EP-1 | GPU scheduling | Platform | P1 | 1 week | CRD fields |
| EP-2 | GPU cost tracking | Platform | P2 | 3-4 weeks | Metrics + billing |

## What's Already There (No Gaps)

- **S3 shared access from multiple pods** — state-proxy mounts same
  `STATE_BUCKET` + `STATE_PREFIX` across actors (works today)
- **CAS conflict detection** — `s3-buffered-cas` detects concurrent writes
  via ETag (works today)
- **Exclusive file creation** — `open("/path", "x")` → `If-None-Match: *`
  (works today)
- **KEDA autoscaling** — queue depth → pod count (works today)
- **FLY streaming** — agents stream progress to gateway (works today)
- **Envelope routing** — agents send messages to each other via MQ (works today)
- **Class handler init** — `__init__()` runs once per pod (workaround for
  init containers, works today)
- **Secret injection** — per-namespace secrets via `secretRefs` (works today)
