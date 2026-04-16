---
description: "Developer experience: any OCI image, GitOps, CI/CD, local Kind testing, CLI tools"
---

# Developer Experience

Asya provides CLI tools and local testing workflows that let developers iterate
without deploying to a Kubernetes cluster.

## The `asya` CLI

The `asya` command-line tool provides subcommands for common development tasks:

| Command | Purpose |
|---------|---------|
| `asya flow compile` | Compile a Python flow to AsyncActor manifests |
| `asya flow graph` | Generate a visual graph (SVG/PNG) of a compiled flow |
| `asya mcp` | Debug MCP tool invocations locally |

## Local testing with Docker Compose

Actors can be tested locally using Docker Compose with the Socket transport. No
cloud credentials, no Kubernetes cluster, no queue provisioning. The Socket
transport uses Unix domain sockets for message passing, making tests fast and
deterministic.

The test hierarchy supports progressive confidence:

1. **Unit tests** — test the handler function directly with `pytest`
2. **Component tests** — single actor in Docker Compose
3. **Integration tests** — multiple actors wired together in Docker Compose
4. **E2E tests** — full stack in a Kind cluster (only for K8s-specific features)

## Flow visualization

The flow compiler can output a visual graph of the compiled actor pipeline.
This makes it easy to verify that the compiler produced the expected routing
before deploying.

```bash
asya flow compile my_flow.py --graph flow.svg
```

## Fits Any Dev Flow

Asya is not opinionated about your tooling. It integrates with what you already use:

- **CI/CD** — standard Helm charts, works with any pipeline (GitHub Actions, GitLab CI, Jenkins)
- **GitOps** — Flux, Argo CD, or any tool that syncs Helm releases from Git
- **Container images** — any Dockerfile, OCI buildpacks, or pre-built images; no custom base image required
- **IaC** — Crossplane for infrastructure, Terraform/Pulumi for cloud resources alongside

## Future roadmap

Planned developer experience improvements:

- VS Code extension for handler development and flow visualization
- Online debugging with Skaffold/Tilt for live cluster iteration
- Shadow deployments for safe production testing
- One-click deploy/undeploy from the CLI

## Further reading

- [CLI component reference](../reference/components/lab-cli.md) — full command
  reference and options
- [Flow Compiler component](../reference/components/lab-flow-compiler.md) —
  compiler internals and output formats
- [Your first actor](../usage/start-first-actor.md) — end-to-end tutorial from
  handler to deployment
