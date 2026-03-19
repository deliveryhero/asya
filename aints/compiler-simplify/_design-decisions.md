# Design Decisions

┌─────┬──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  #  │                                                           Decision                                                           │
├─────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 1   │ Flow is always required — no standalone actor visualization. Even single actors need a flow wrapper.                         │
├─────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 2   │ Yield analysis overrides flow routes — graph shows actual runtime routing, not declared intent.                              │
├─────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 3   │ Full recompile always — idempotent, never overwrites kustomize overlays.                                                     │
├─────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 4   │ 1:N via graph UI — DS clicks actor nodes to customize name/config, writes to kustomize overlay.                              │
├─────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 5   │ Config schema from XRD — actor edit UI reads OpenAPI schema from AsyncActor XRD.                                             │
├─────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 6   │ Flow composition = compile-time inlining — inner flow expanded, visual grouping in graph, all actors get outer flow's label. │
├─────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 7   │ Smart entrypoint — compiler marks first user actor as entrypoint (no empty start router).                                    │
├─────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 8   │ External handlers = best-effort — yield analysis if source available, opaque node otherwise.                                 │
├─────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 9   │ Files-first — compile writes files, asya serve manages lifecycle + REST API.                                                 │
├─────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 10  │ Two compilation models — batch (CLI) and interactive (asya serve + UI/notebook).                                             │
└─────┴──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

User Workflow Catalog

W1: New flow (script)
DS writes flow.py → asya compile flow.py → sees graph → clicks actors to configure → deploy

W2: Edit flow (iterate)
DS edits flow.py → asya compile flow.py → regenerated routers + base manifests, overlays preserved

W3: Edit handler (iterate)
DS edits handler_a.py → asya compile flow.py → full recompile, handler yields re-analyzed

W4: Notebook development
DS edits flow cell → %asya compile or compile() → graph renders inline → configure via UI → deploy

W5: Flow composition
DS writes flow_a calling flow_b → compile inlines flow_b → single flat actor graph with visual groups

W6: Actor config customization
DS sees graph → clicks actor node → edits config (replicas, timeout, resources) → overlay written

W7: Multi-team monorepo
team1/.asya/config.yaml overrides repo root. DS runs compile from team1/ — nearest config wins.
