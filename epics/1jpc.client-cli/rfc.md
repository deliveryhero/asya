# RFC: Client CLI, Python SDK, and Jupyter Magics

**Status**: Superseded
**Superseded by**: 1jux (asya-lab)
**Date**: 2026-02-26

---

This RFC has been superseded. All content has been merged into the
[asya-lab RFC](../1jux.asya-lab/rfc.md) with the following additions:

- Package renamed from `asya` to `asya-lab` (PyPI name conflict)
- Flow deployment implementation (label convention, 1:M constraint, router
  flavors, `--keep-processors`)
- Flow exposure mechanics (`asya flow expose`, ConfigMap patching, fsnotify)
- Deploy/undeploy semantics (context-dependent behavior, K8s safety rule)
- Protocol handling (`--protocol=mcp|a2a`)
- Expanded Jupyter magics (context auto-processing, visualization options)
- Migration module table (line-by-line inventory of asya-cli)

See [1jux.asya-lab/rfc.md](../1jux.asya-lab/rfc.md) for the current design.
