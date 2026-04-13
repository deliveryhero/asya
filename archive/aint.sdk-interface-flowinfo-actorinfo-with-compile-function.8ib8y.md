---
title: "SDK interface: FlowInfo + ActorInfo with compile() function"
status: rejected
priority: 2
parent: pj0fo
dependencies:
  - o8ql
---

Implement compile() SDK function returning FlowInfo (renamed from CompileResult). FlowInfo attributes: flow_name, routers_path, manifests_dir, graph (dict), dot (str), mermaid (str), svg (str|None), actors (list[ActorInfo]), warnings. ActorInfo extends existing templater.ActorInfo: name, handler, image, flow_role, env, is_generated (renamed from is_router), manifest_path, source_file, source_line, handler_local. SDK mirrors CLI exactly. See RFC section: SDK interface.
