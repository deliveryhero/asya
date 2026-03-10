---
title: "ADR: DS Configuration Management Research"
status: informational
date: 2026-02-26
---

# DS Configuration Management Research

Research on how popular DS/ML frameworks handle configuration (env vars, secrets,
per-environment settings) across local development and production. Saved for
future reference when Asya matures and may consider deeper config integration.

## Current Decision

Asya keeps it simple: handlers use `os.environ.get("X", "default")`, `.env`
files loaded via standard `load_dotenv`, resolution order configurable in
`asya.yaml`. No framework-imposed config pattern.

## Framework Survey

### Kedro (McKinsey/QuantumBlack)
- **Format**: YAML files using OmegaConf
- **Structure**: `conf/base/` (committed) + `conf/local/` (gitignored) + per-env folders
- **Secrets**: Dedicated `credentials.yml` (auto-gitignored), `${oc.env:VAR}` syntax
- **Validation**: OmegaConf schema, `ValueError` on duplicates/missing vars
- **Strength**: Clean hierarchy, strict credential separation

### Hydra (Meta)
- **Format**: YAML config groups with hierarchical composition
- **Selection**: Override from CLI: `python train.py db=postgresql model=vit`
- **Secrets**: `${env:VAR_NAME}` syntax in YAML
- **Strength**: Config composition without file proliferation, great for ML hyperparams

### Dagster
- **Format**: Pydantic `ConfigurableResource` classes
- **Env vars**: `EnvVar` class (evaluated at run launch, secrets hidden in UI)
- **Validation**: Pydantic `ValidationError`, type-safe config editor with typeahead
- **Strength**: Self-documenting via Pydantic `Field` descriptions

### Metaflow (Netflix)
- **Format**: TOML/JSON files or Python dicts, `@config` decorator
- **Key property**: Configs resolved at deployment time (immutable once deployed)
- **Validation**: Pydantic integration for schema validation
- **Strength**: Deployment-time immutability prevents config drift

### ZenML
- **Format**: YAML + Python SDK
- **Secrets**: First-class centralized secrets store (AWS/GCP/Azure/Vault backends)
- **Strength**: Pluggable secrets backends, HA with secondary store

### Prefect
- **Format**: `prefect.yaml`, `pyproject.toml`, `.env` files
- **Env vars**: `{{ $ENV_VAR_NAME }}` template syntax in YAML
- **Strength**: `.env` support, profiles, env vars always take precedence

### BentoML
- **Format**: `bentofile.yaml` or `pyproject.toml`
- **Secrets**: Define env var name without value in config, inject at deployment
- **Strength**: Clean separation of config-time vs deploy-time secrets

### Hamilton (DAGWorks)
- **Format**: Python dictionaries, `@config.when()` decorator
- **Strength**: Config-based function selection (no if/else branching)

## Common Patterns

### Config hierarchy (most frameworks)
1. Base config (committed to git)
2. Environment-specific overrides (prod, staging, dev)
3. Local overrides (gitignored)
4. Environment variables (highest precedence)

### Self-documenting config
- Pydantic BaseSettings is the industry standard for Python (Dagster, Prefect)
- OmegaConf for YAML interpolation (Kedro, Hydra)
- Config classes with typed fields and descriptions

### .env file usage
- Dagster: supported since v1.1.0
- Prefect: supported since v3.0.5
- Kedro: does NOT use .env (OmegaConf resolvers instead)
- Hydra: does NOT use .env (YAML + env interpolation)

## Future Integration Options for Asya

When Asya matures, consider:

1. **OmegaConf/Hydra integration** for hierarchical YAML config with interpolation
2. **Pydantic BaseSettings** for typed handler config classes (optional, opt-in)
3. **Kedro-style conf/ hierarchy** if project structure needs more structure
4. **Centralized secrets store** integration (Vault, AWS Secrets Manager)

These should be opt-in additions, not replacements for the current simple approach.
