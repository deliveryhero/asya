

The Four Stages

COMPILE TIME          BUILD TIME           DEPLOY TIME          RUNTIME
─────────────         ──────────           ───────────          ───────
Python: YES(*)        Python: NO           Python: NO           Python: YES
Input: flow.py        Input: code+config   Input: manifests     Input: envelope
Output: routers.py,   Output: OCI image    Output: running      Output: response
manifests, build      in registry          pods
configs

(*) Jupyter: kernel
    CLI: --python /path/to/venv/bin/python

Stage 1: Compile Time

Available: A Python interpreter (either the Jupyter kernel, or one pointed to via CLI flag).

What we resolve using Python:

# The compiler CURRENTLY does AST-only:
p = validate_order(p)  →  "validate_order"  (string)

# What it SHOULD do: use Python to resolve handler → filesystem path:
import importlib.util
spec = importlib.util.find_spec("my_handlers.validate_order")
# → /home/user/project/src/my_handlers/validate_order.py

# Then match filesystem path → build-context from asya.yaml

What gets generated:
1. routers.py — with resolve("validate_order") calls (deferred to runtime)
2. Build configs — which source directories go into which images
3. Manifests — AsyncActor YAMLs with ASYA_HANDLER_* env vars mapping handler refs to actor names

Key distinction: Handler name ≠ actor name. resolve("validate_order") at runtime uses ASYA_HANDLER_VALIDATE_ORDER env var to find the actor name. The env var value IS the
full Python import path. The env var NAME (uppercased, underscored) derives the actor name.

Stage 2: Build Time

Available: Docker/apko/buildpacks. No live Python.

Input: The build configs generated at compile time, plus the source code itself.

What happens: Mechanically build images from the contexts specified by compile-time output. No Python resolution needed — everything was resolved at compile time.

Stage 3: Deploy Time

Available: kubectl/flux/argocd. No Python.

Input: Manifests generated at compile time, images from build time.

What happens: Apply manifests. Actor names, env vars, image refs are all baked in.

Stage 4: Runtime

Available: Full Python inside the container.

What happens:
- asya_runtime.py imports handler via ASYA_HANDLER
- Routers call resolve() using ASYA_HANDLER_* env vars
- Python does the actual import resolution (importlib)

The asya.yaml Role

Given these stages, asya.yaml is the compile-time bridge between Python's module system and the build system:
```yaml
# asya.yaml — maps Python packages to build contexts
build-contexts:
- python: "my_handlers"                    # Python package/module
    context: "./src/my_handlers"             # Filesystem root for build
    image: "ghcr.io/org/my-handlers:${tag}"  # Image template
    build:
        local: ...                             # How to build locally
        remote: ...                            # How to build on-cluster

- python: "gpu_models"
    context: "./src/gpu_models"
    image: "ghcr.io/org/gpu-models:${tag}"
    build:
        local: docker build -f Dockerfile .
```
At compile time, when the compiler sees p = validate_order(p) and Python resolves it to /project/src/my_handlers/validate_order.py, it matches the my_handlers build-context

---

So the resolution chain at compile time is:

Flow source (AST)
    ↓ extract handler names
Handler refs: ["validate_order", "Model.predict", "my_handlers.process"]
    ↓ Python import resolution (importlib.util.find_spec)
File paths: ["/proj/src/handlers/validate.py", "/proj/src/ml/model.py", "/proj/src/handlers/process.py"]
    ↓ match to asya.yaml build-contexts
Build contexts: {"handlers" → ghcr.io/org/handlers, "ml" → ghcr.io/org/ml-model}

This means the compiler needs a Python environment. Two modes:

┌─────────┬───────────────────────────────────────────────────┬──────────────────────────────┐
│  Mode   │                   Python source                   │             When             │
├─────────┼───────────────────────────────────────────────────┼──────────────────────────────┤
│ Jupyter │ Current kernel (sys.executable)                   │ %asya flow compile magic     │
├─────────┼───────────────────────────────────────────────────┼──────────────────────────────┤
│ CLI     │ Auto-detect from uv/active venv, or --python flag │ asya flow compile my_flow.py │
└─────────┴───────────────────────────────────────────────────┴──────────────────────────────┘

DS working in notebooks get resolution "for free" — their kernel already has all the sys.path hacks applied. CLI users must
have clean, importable packages.

Now, the key question is what compile time produces beyond routers.py. I see three outputs:

1. Router code (routers.py) — already exists
2. Manifest templates (asyncactor-*.yaml) — AsyncActor CRDs with image refs from asya.yaml, handler env vars
3. Build plan — which images need building, from which contexts, using which strategy

The build plan is the new piece. It connects compile output to asya build:
```yaml
# .asya/build-plan.yaml (generated at compile time)
images:
- ref: "ghcr.io/org/handlers:${tag}"
    context: "./src/handlers"
    strategy: apko
    config: "./src/handlers/apko.yaml"
    handlers:
    - validate_order
    - process

- ref: "ghcr.io/org/ml-model:${tag}"
    context: "./src/ml"
    strategy: dockerfile
    config: "./src/ml/Dockerfile"
    handlers:
    - Model.predict
```