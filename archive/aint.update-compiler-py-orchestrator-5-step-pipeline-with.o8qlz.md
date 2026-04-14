---
title: "Update compiler.py orchestrator: 5-step pipeline with AsyaProject integration"
status: rejected
priority: 1
dependencies:
  - qnyz2
  - p2d0s
  - h6gnt
  - u7wr9
---

Rewrite compiler.py orchestrator to implement the 5-step pipeline: Parse -> CodeGen -> Manifests -> Analyze -> GraphGen. Integrate with AsyaProject for config-driven paths: compiler.routers (resolve_path), compiler.manifests (resolve_path), build[].module/image (resolve_image), templates.* (build_template_context). FlowCompiler receives AsyaProject instance. CLI creates via from_dir(), SDK receives from caller. Returns FlowInfo (renamed from CompileResult). See RFC sections: Compiler pipeline, AsyaProject integration.
