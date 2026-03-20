---
title: Review all docs against Diataxis framework
priority: 2 # medium
assignee: Artem Yushkovskiy
---


Audit the full docs/ tree against the Diataxis framework (https://diataxis.fr):

Four quadrants:
- Tutorials: learning-oriented, teach by doing
- How-to guides: task-oriented, practical steps
- Reference: information-oriented, accurate description
- Explanation: understanding-oriented, background context

Goals:
1. Classify every existing doc into one of the four quadrants
2. Identify docs that mix quadrants (most common issue)
3. Identify gaps -- missing quadrants for key features
4. Produce a short remediation plan: rename, split, or rewrite

Scope:
- docs/features/: likely explanations/how-to, check for tutorial leakage
- docs/architecture/: likely reference + explanation
- docs/tutorials/: verify these are actually tutorials (not how-to)
- docs/reference/: verify completeness and accuracy-orientation
- docs/internal/: not user-facing, skip Diataxis but check consistency
- docs/quickstart/: typically tutorial quadrant, verify

Output:
- Classification table (file, quadrant, issues)
- List of files to split/rename
- List of missing docs to create
- No rewrites in this aint -- just the audit and plan

---

## Audit Results

Audited 48 files in `docs/` (excluding `docs/plans/`, `docs/comparisons/`, `docs/mkdocs/`,
`docs/img/`). Classified each against the four Diataxis quadrants.

### Classification Table

#### docs/ (top-level)

| File | Quadrant | Mixed In | Issues |
|------|----------|----------|--------|
| README.md | Reference | — | Stub — navigation hub only, no "start here" guidance |
| concepts.md | Explanation | Reference | Well-structured; strong conceptual foundation |
| motivation.md | Explanation | — | Clean; good design rationale and positioning |

#### docs/quickstart/

| File | Quadrant | Mixed In | Issues |
|------|----------|----------|--------|
| README.md | Tutorial | How-to | Mixes setup tutorial with optional production guidance |
| usage.md | Tutorial | Reference, How-to | Multiple modes without separation; Flow DSL reference dump embedded in tutorial flow |

#### docs/tutorials/

| File | Quadrant | Mixed In | Issues |
|------|----------|----------|--------|
| actor-flavors.md | Tutorial | Reference | Good balance; reference elements are contextual |
| actor-handler-adapter-pattern.md | Tutorial | How-to, Reference | Excellent structure; reference well-integrated |
| agentic-patterns.md | Tutorial | Reference, Explanation, How-to | 660 lines mixing modes; explanation sections appropriate for learning arc but could be split |

#### docs/reference/

| File | Quadrant | Mixed In | Issues |
|------|----------|----------|--------|
| abi-protocol.md | Reference | Tutorial | Testing patterns section leans tutorial; otherwise excellent |
| flow-dsl.md | Reference | Explanation, How-to | 990 lines mixing 5 concerns; "What problem does it solve?" and compiler architecture belong in explanation docs |

#### docs/features/

| File | Quadrant | Mixed In | Issues |
|------|----------|----------|--------|
| resiliency.md | Reference | How-to | Mixes config tables with practical recipes; could separate reference from how-to |
| task-pause.md | Explanation | How-to, Reference | Multi-faceted feature justifies mixed approach; consider splitting route config into how-to |

#### docs/install/

| File | Quadrant | Mixed In | Issues |
|------|----------|----------|--------|
| aws-eks.md | How-to | Reference | Good procedural guide; large IAM policy blocks could be extracted to reference |
| gcp-gke.md | How-to | Reference | 675 lines; credential types and WI ordering could move to reference |
| helm-charts.md | Reference | How-to | Values tables + installation examples; primarily reference |
| local-kind.md | How-to | Reference | Good procedural guide for local dev |

#### docs/operate/

| File | Quadrant | Mixed In | Issues |
|------|----------|----------|--------|
| monitoring.md | Reference | How-to | Metrics tables + dashboard setup; reference-first |
| scaling.md | Reference | Explanation | Stub — only 57 lines; too brief |
| troubleshooting.md | How-to | Reference | Strong symptom-to-solution structure |
| upgrades.md | How-to | Reference | Short but adequate procedural steps |

#### docs/architecture/

| File | Quadrant | Mixed In | Issues |
|------|----------|----------|--------|
| README.md | Explanation | Reference | Good entry point; system overview with diagrams |
| asya-actor.md | Reference | How-to | Missing config examples for typical actor patterns |
| asya-crew.md | Reference | Explanation | Long; blends architectural detail with reference tables |
| asya-crossplane.md | Reference | Explanation | Dense; assumes Crossplane familiarity; lacks setup how-to |
| asya-flow.md | Explanation | Reference | Target audience unclear (users vs maintainers) |
| asya-gateway.md | Reference | How-to, Explanation | Mixes route reference with architectural decisions |
| asya-lab.md | How-to | Reference | Stub — very short; only basic CLI usage |
| asya-runtime.md | Reference | How-to | Long; mixes quick-start with config table |
| asya-sidecar.md | Reference | Explanation | Dense (394 lines); "how it works" mixed with reference |
| asya-state-proxy.md | Reference | How-to, Explanation | Very long (492 lines); limitations section is tutorial-like |
| autoscaling.md | How-to | Reference | Good balance; KEDA configuration focus |
| observability.md | Reference | How-to | Stub for gateway metrics; incomplete |
| protocols/actor-actor.md | Reference | Explanation | Comprehensive; design rationale sections mixed in |
| protocols/sidecar-runtime.md | Reference | How-to | Good reference; curl examples add light how-to |
| transports/README.md | Reference | Explanation | Minimal; mostly navigation |
| transports/rabbitmq.md | Reference | How-to | Practical deployment section (Helm commands) |
| transports/socket.md | Reference | How-to, Explanation | Docker Compose example elevates to mixed how-to |
| transports/sqs.md | Reference | How-to | IAM policies and cost considerations |

#### docs/internal/ (not user-facing — consistency check only)

| File | Quadrant | Mixed In | Issues |
|------|----------|----------|--------|
| README.md | Explanation | — | Brief meta-guide; appropriate |
| actor-flavors.md | Reference | Explanation | Slightly repetitive with tutorials/actor-flavors.md; deeper |
| crew-checkpointer.md | Reference | Explanation, Tutorial | Future section signals living document |
| crew-termination.md | Reference | — | Brief pure lookup table; well-scoped |
| gateway-api-spec.md | Reference | — | Well-organized; 732 lines, comprehensive |
| gateway-security.md | Reference | Explanation, How-to | Mixed intentionally for security context |
| resiliency.md | Reference | Explanation | Good structure; algorithm explanation appropriate |
| testing-a2a.md | Reference | How-to | Infrastructure setup guidance contextual |
| testing-state-proxy.md | Reference | How-to | Backend addition guidance appropriate |
| testing-transport.md | Reference | How-to | Dense but comprehensive |

### Quadrant Distribution (user-facing docs only, excluding internal/)

| Quadrant | Count | Files |
|----------|-------|-------|
| Tutorial | 5 | quickstart/README, quickstart/usage, tutorials/* (3) |
| How-to | 7 | install/aws-eks, install/gcp-gke, install/local-kind, operate/troubleshooting, operate/upgrades, architecture/autoscaling, architecture/asya-lab |
| Reference | 19 | architecture/* (13), reference/* (2), features/resiliency, install/helm-charts, operate/monitoring, operate/scaling |
| Explanation | 5 | README, concepts, motivation, architecture/README, architecture/asya-flow, features/task-pause |

**Imbalance**: Reference dominates (53%), Explanation and Tutorial are thin (14% each), How-to is moderate (19%). A healthy Diataxis distribution has roughly equal coverage across quadrants for each major feature.

---

### Files to Split or Rename

| File | Action | Rationale |
|------|--------|-----------|
| reference/flow-dsl.md (990 lines) | **Split** | Extract "What problem does it solve?" and "How Asya executes flows: CPS" into a new `explanation/flow-compilation.md`; keep syntax rules and IR spec as reference |
| tutorials/agentic-patterns.md (660 lines) | **Split** | Extract "Core concepts" / "Flow vs Actor" table into `explanation/agentic-design.md`; keep pattern walkthroughs as tutorial; extract quick-reference tables into `reference/agentic-cheatsheet.md` |
| quickstart/usage.md | **Split** | Separate local testing tutorial from deployment how-to; extract Flow DSL example into reference link |
| features/resiliency.md | **Split** | Extract practical recipes into `howto/configure-retries.md`; keep config tables as reference |
| features/task-pause.md | **Split** | Extract route configuration steps into `howto/setup-pause-resume.md`; keep lifecycle explanation |
| architecture/asya-state-proxy.md (492 lines) | **Split** | Extract "limitations" into a how-to or FAQ; keep architecture reference |
| architecture/asya-gateway.md | **Split** | Extract deployment steps and tool registration into `howto/register-gateway-tools.md` |
| architecture/asya-lab.md | **Rename/Expand** | Move to `reference/cli.md` — it's a CLI reference, not architecture |
| architecture/autoscaling.md | **Rename** | Move to `howto/configure-autoscaling.md` — it's task-oriented |
| operate/scaling.md | **Merge or Expand** | Merge into autoscaling.md or expand; 57 lines is too thin |

### Missing Documentation

#### Tutorials (highest gap)

| Missing Doc | Description |
|-------------|-------------|
| tutorials/first-actor.md | "Build your first actor" — minimal echo actor from scratch, deploy to Kind, send a message, see the result |
| tutorials/first-pipeline.md | "Build your first pipeline" — chain two actors, observe envelope routing |
| tutorials/first-flow.md | "Write your first flow" — Python Flow DSL from scratch, compile, deploy |
| tutorials/pause-resume.md | "Add human-in-the-loop to your pipeline" — hands-on pause/resume walkthrough |

#### How-to Guides (moderate gap)

| Missing Doc | Description |
|-------------|-------------|
| howto/add-new-actor.md | Practical steps: write handler, create AsyncActor manifest, deploy, verify |
| howto/configure-retries.md | Extract from features/resiliency.md — step-by-step retry policy setup |
| howto/setup-pause-resume.md | Extract from features/task-pause.md — route configuration steps |
| howto/configure-autoscaling.md | Consolidate architecture/autoscaling.md + operate/scaling.md |
| howto/register-gateway-tools.md | Extract from architecture/asya-gateway.md — ConfigMap tool registration |
| howto/debug-envelope.md | Trace an envelope through the mesh (logs, metrics, curl sidecar) |
| howto/add-transport.md | Extract from internal testing docs — adding a new transport backend |

#### Explanation (moderate gap)

| Missing Doc | Description |
|-------------|-------------|
| explanation/choreography-vs-orchestration.md | Why Asya chose choreography; trade-offs vs LangGraph/CrewAI orchestrators |
| explanation/flow-compilation.md | How the Flow DSL compiler transforms Python to CPS message chains (extract from flow-dsl.md) |
| explanation/envelope-design.md | Why route.prev/curr/next; why immutable IDs; why payload is opaque |
| explanation/agentic-design.md | How Asya maps to agentic patterns; "Flow vs Actor" decision guide (extract from agentic-patterns.md) |

#### Reference (minor gap — already strong)

| Missing Doc | Description |
|-------------|-------------|
| reference/cli.md | Full CLI reference for `asya` commands (currently stub in architecture/asya-lab.md) |
| reference/env-vars.md | Consolidated env var reference across all components (currently scattered) |
| reference/asyncactor-crd.md | Full CRD field reference (partially in architecture/asya-actor.md but mixed with explanation) |

---

### Remediation Plan (Priority Order)

**Phase 1 — Split oversized mixed docs** (no new content, just reorganize)
1. Split `reference/flow-dsl.md` → keep reference + new `explanation/flow-compilation.md`
2. Split `tutorials/agentic-patterns.md` → keep tutorial + new `explanation/agentic-design.md` + new `reference/agentic-cheatsheet.md`
3. Split `features/resiliency.md` → keep reference + new `howto/configure-retries.md`
4. Split `features/task-pause.md` → keep explanation + new `howto/setup-pause-resume.md`
5. Move `architecture/asya-lab.md` → `reference/cli.md` (expand)
6. Consolidate `architecture/autoscaling.md` + `operate/scaling.md` → `howto/configure-autoscaling.md`

**Phase 2 — Fill tutorial gaps** (highest user impact)
1. Write `tutorials/first-actor.md`
2. Write `tutorials/first-pipeline.md`
3. Write `tutorials/first-flow.md`
4. Write `tutorials/pause-resume.md`

**Phase 3 — Fill how-to and explanation gaps**
1. Write `howto/add-new-actor.md`
2. Write `howto/debug-envelope.md`
3. Write `explanation/choreography-vs-orchestration.md`
4. Write `explanation/envelope-design.md`
5. Write `reference/env-vars.md` (consolidate from scattered sources)
6. Write `reference/asyncactor-crd.md`

**Phase 4 — Polish**
1. Expand `docs/README.md` with a "start here" flow diagram
2. Expand `operate/scaling.md` or merge into autoscaling how-to
3. Complete `architecture/observability.md` gateway metrics section
4. Add Diataxis quadrant labels to each doc's frontmatter or header
