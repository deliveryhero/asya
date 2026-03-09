---
title: "ADR: Custom composition function for actor flavors"
status: accepted
date: 2026-03-09
---

# ADR: Why function-asya-flavors requires a custom OCI image

## Context

Asya actors support "flavors" — reusable EnvironmentConfig bundles that
platform teams create to pre-configure actors (e.g., `openai-secrets` mounts
API keys, `persistence-s3` configures state proxy). Actors reference flavors
by name in `spec.flavors: [openai-secrets, persistence-s3]`, and the
composition pipeline resolves, merges, and applies them.

We evaluated whether stock Crossplane functions could replace the custom
`function-asya-flavors` Go module.

## Decision

Keep a custom composition function (`function-asya-flavors`) packaged as a
separate OCI image. Simplify its merge logic to ~30 lines (env-var merge by
`name` key) instead of the full `strategicpatch` machinery.

## Rationale

Two capabilities are missing from stock Crossplane functions.

### 1. Dynamic resource fetching by variable-length list

The actor's `spec.flavors` is a variable-length array (up to 8 items). For
each flavor name, the function must fetch an EnvironmentConfig matched by
label `asya.sh/flavor=<name>`.

**`function-go-templating` cannot do this.** It is a pure renderer — data in,
templates out. It has no access to the Crossplane Requirements API, which is
the mechanism for a function to tell Crossplane "fetch these cluster resources
and provide them on the next reconciliation loop."

**`function-environment-configs` cannot do this either.** It supports
`fromCompositeFieldPath` for label values, but requires a fixed number of
selector entries defined at composition-write time. It cannot iterate a
variable-length `spec.flavors[]` array. Pre-reserving N slots (one per
possible flavor index) is fragile and verbose. Pre-reserving would work fine
if only lists could be merged (critical for env lists - env vars defined in
different flavors must be joined together in a long list, not overwritten
by the next flavor).

Only a custom function using the Requirements API can dynamically request N
EnvironmentConfigs based on runtime XR state.

### 2. Array merge by key across EnvironmentConfigs

When multiple flavors set env vars on the same container, the arrays must
merge by `name` key (same name = last wins, different names = accumulate).

**`function-environment-configs`** merges multiple EnvironmentConfigs via
standard JSON deep merge. Arrays are replaced entirely — the last
EnvironmentConfig's `env` array overwrites all previous ones. There is no
configuration option for append or merge-by-key behavior.

**`function-patch-and-transform`** offers `MergeObjectsAppendArrays` and
`ForceMergeObjectsAppendArrays` policies, but these blindly append (no
dedup by key). Two flavors setting `FOO=1` and `FOO=2` would produce
duplicate entries, not an override. There is no merge-by-key policy.
Additionally, `CombineFromEnvironment` produces strings, not arrays — it
cannot flatten multiple arrays into one.

Relevant upstream issues:
- crossplane/crossplane#4738 (closed/stale): discussed simplifying the
  environment model, no resolution on array merge
- crossplane-contrib/function-patch-and-transform#127 (open): users report
  `AppendArrays` policy broken for `CombineFromComposite`
- crossplane-contrib/function-patch-and-transform#75 (closed): maintainer
  suggested SSA would handle merge at schema level, but this only applies to
  managed resources with proper CRD merge keys, not arbitrary composition
  context

### What would eliminate the need for this custom function

If Crossplane added **either** of the following, `function-asya-flavors`
could be replaced by stock functions:

1. **`function-environment-configs` with merge-by-key policy for arrays** —
   a configuration option like `arrayMergeStrategy: mergeByKey` with a
   configurable key field (defaulting to `name` for env vars). This would
   allow multiple EnvironmentConfigs to contribute env vars to the same
   container without overwriting.

2. **`function-environment-configs` with per-config context keys** — instead
   of merging all EnvironmentConfigs into one blob at
   `apiextensions.crossplane.io/environment`, write each to a separate
   context key. Then `function-go-templating` or `function-patch-and-transform`
   could merge them with appropriate strategies downstream.

Neither is on the Crossplane roadmap as of March 2026.

## Consequences

- We maintain ~500 lines of Go (including tests) as a custom Crossplane
  function, packaged and versioned as a separate OCI image.
- The function's merge logic is minimal: simple JSON deep merge for all
  fields, with one special case for env var lists (~30 lines).
- If Crossplane adds array-merge-by-key to `function-environment-configs`,
  we can drop the custom function entirely.
- Namespace-scoped flavors (via ConfigMaps instead of cluster-scoped
  EnvironmentConfigs) tracked separately in [jgwn].
