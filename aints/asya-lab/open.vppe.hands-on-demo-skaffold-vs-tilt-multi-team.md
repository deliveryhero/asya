---
title: "Hands-on demo: Skaffold vs Tilt for multi-team actor repos"
priority: 1 # high
---

## Context

Asya is adopting a build tool (Skaffold or Tilt) as the source of truth for "which source directories produce which container images." The compiler reads this mapping to resolve handler functions to images. Before committing to one tool, we need a hands-on comparison with a realistic multi-team project structure deployed to a real GKE cluster.

See `research-build-system.md` (D2: Skaffold as source of truth) for the design context.

## Goal

Build two parallel demo projects — one Skaffold-based, one Tilt-based — that exercise the same scenarios against a real K8s cluster. Compare DX, debuggability, and integration complexity. The demos should be realistic enough to inform the final tool choice.

## Demo Structure

```
examples/
  demo-skaffold/
    .asya/config.yaml
    skaffold.yaml                  # root, requires: team-a, team-b
    team-a/
      .asya/config.yaml           # team-a overrides
      skaffold.yaml               # team-a artifacts
      actors/
        sentiment/
          Dockerfile
          pyproject.toml
          sentiment_actors/
            __init__.py
            handler.py             # def analyze(p): ...
        summarizer/
          Dockerfile
          summarizer/
            __init__.py
            handler.py             # def summarize(p): ...
      flows/
        pipeline.py                # flow: analyze -> summarize
    team-b/
      .asya/config.yaml
      skaffold.yaml
      actors/
        translator/
          Dockerfile
          translator/
            __init__.py
            handler.py
    libs/
      common/
        pyproject.toml             # shared lib (S5 scenario)
        common/
          __init__.py
          utils.py

  demo-tilt/
    (mirror structure with Tiltfile instead of skaffold.yaml)
    Tiltfile                       # root, load() sub-tiltfiles
    team-a/
      Tiltfile
      ...
    team-b/
      Tiltfile
      ...
```

## Scenarios to Exercise

### S1: Basic build + deploy
- Build all artifacts
- Deploy to GKE namespace
- Verify actors process messages

### S2: Multi-config / multi-team
- Each team has its own config file
- Root config aggregates (skaffold `requires:` vs tilt `load()`)
- Teams can build independently

### S3: Dev loop (live reload)
- `skaffold dev` vs `tilt up`
- Edit handler code -> observe rebuild + redeploy
- File sync vs full rebuild behavior

### S4: Shared library (S5 from research)
- `libs/common/` used by team-a actors
- Build context must include shared lib
- Verify Griffe resolves `common.utils` correctly (not `libs.common.common.utils`)

### S5: Pod debugging
- Attach to running actor pod
- View logs, inspect env vars
- Test with `kubectl exec` / tilt resource inspection

### S6: Pre-built image reference
- External image not built by either tool
- How does each tool handle "I need this image but don't build it"?

## Evaluation Criteria

| Criterion | Weight | Notes |
|-----------|--------|-------|
| Config parsability (can asya read without binary?) | High | Skaffold YAML vs Tilt Starlark |
| Multi-config ergonomics | High | How natural is the multi-.asya/ pattern? |
| Dev loop quality (rebuild speed, file sync) | Medium | DS iteration speed |
| Scaffolding safety (additive generation) | High | Can asya generate config without overwriting? |
| Pre-built image support | Medium | Corner case but needed |
| Community + maintenance trajectory | Medium | Long-term viability |
| Learning curve for DS users | Medium | Who edits the config? |

## Deliverables

1. Working `examples/demo-skaffold/` with README
2. Working `examples/demo-tilt/` with README
3. Comparison write-up in this aint file (updated after demo)
4. Recommendation with rationale

## Dependencies
- GKE cluster access (or kind cluster for initial testing)
- `research-build-system.md` decisions
- `asya-lab/bggr` (ConfigMap-mount pattern — for single-file actor scenario in demo)

## Open Questions
1. Should the demo include a Jupyter notebook scenario (DS compiling from notebook)?
2. Should we test Tilt extensions (custom Python/Starlark) for asya-specific workflows?
3. How to handle registry auth in both tools for the demo?
