---
title: Refactor documentation structure and consolidate quickstart
priority: 2 # medium
tags:
  - type:bug
---




Refactor the documentation structure to improve clarity and maintainability:

**Part 1: Move internal docs to _internal/**
- Create docs/_internal/ directory
- Move docs/rfc/ → docs/_internal/rfc/
- Move docs/mkdocs/ → docs/_internal/mkdocs/
- Move docs/stylesheets/ → docs/_internal/stylesheets/
- Update any references to moved directories

**Part 2: Consolidate quickstart guides**
Replace the confusing split between 'for data scientists' and 'for platform engineers' with a single progressive quickstart in docs/quickstart/README.md:

Split into these sections:
1. Prerequisites
   - Kind cluster setup (or any K8s cluster)
   - Required tools (kubectl, helm, asya CLI)
   
2. Bare minimal setup
   - Plain Kubernetes manifests approach
   - Step-by-step deployment
   
3. Flow DSL quickstart (optional)
   - asya flow compile user flow example
   - Simple pipeline demonstration
   
4. Advanced deployment (optional)
   - Flow that hides deployment details
   - Production considerations

**Success criteria:**
- Single clear path for all users (no role-specific guides)
- Progressive complexity (start simple, add advanced features)
- All internal docs in _internal/
- No broken links


---
_Migrated from beads `asya-ab2`_
