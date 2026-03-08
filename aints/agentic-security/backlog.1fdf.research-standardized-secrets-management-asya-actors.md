---
title: "External secrets integration: Vault, ESO, cloud secret managers (post-v0)"
priority: 3 # low — post-v0; basic k8s Secrets in [wcnw]
tags:
  - type:feature
dependencies:
  - agentic-security/wcnw
---




## Research Objective

Design a secrets management approach for Asya actors that:
- Avoids explicit secrets in environment variables
- Integrates with external secret providers (Vault, AWS Secrets Manager, etc.)
- Uses standardized, CNCF-supported patterns
- Provides a simple Asya-native interface for referencing secrets

## Problem Statement

**Current state:**
Actors needing API keys (OpenAI, cloud services, databases) must either:
1. Use K8s Secrets mounted as env vars → Security concerns (etcd storage, RBAC complexity)
2. Hardcode in code/config → Obviously bad
3. Implement custom secret fetching → Every actor reinvents the wheel

**What users want:**
```yaml
apiVersion: asya.dev/v1alpha1
kind: AsyncActor
metadata:
  name: openai-summarizer
spec:
  secrets:
    - name: OPENAI_API_KEY
      from: vault://secret/data/openai#api_key
    # or
    - name: DB_PASSWORD  
      from: aws-secretsmanager://prod/database#password
```

Actor code just reads `os.environ["OPENAI_API_KEY"]` - no secret fetching logic.

## CNCF Landscape Options

### 1. External Secrets Operator (ESO)
- **Status:** CNCF Sandbox → Incubating (graduated?)
- **GitHub:** https://github.com/external-secrets/external-secrets
- **How it works:** 
  - `ExternalSecret` CRD references external provider
  - Operator syncs to K8s Secret
  - Pods mount K8s Secret normally
- **Providers:** Vault, AWS SM, GCP SM, Azure KV, 1Password, many more
- **Pros:** Mature, widely adopted, multi-provider
- **Cons:** Still uses K8s Secrets as intermediate (etcd storage)

### 2. Secrets Store CSI Driver
- **Status:** CNCF project
- **GitHub:** https://github.com/kubernetes-sigs/secrets-store-csi-driver
- **How it works:**
  - CSI driver mounts secrets directly from provider
  - No K8s Secret created (optional sync)
  - Secrets appear as files in pod
- **Providers:** Vault, AWS, Azure, GCP (via provider plugins)
- **Pros:** No intermediate K8s Secret, direct mount
- **Cons:** CSI driver per node, more infra complexity

### 3. HashiCorp Vault (direct)
- **Status:** Not CNCF, but industry standard
- **Options:**
  - Vault Agent Injector (sidecar injects secrets)
  - Vault CSI Provider (with CSI driver)
  - Direct API calls from actor code
- **Pros:** Full Vault features (dynamic secrets, leasing)
- **Cons:** Vault-specific, operational overhead

### 4. SPIFFE/SPIRE for identity
- **Status:** CNCF Graduated
- **Role:** Workload identity, not secret storage
- **Relevance:** Could provide identity for Vault auth, AWS IRSA alternative

## Key Research Questions

### 1. What's the "golden stack"?

Evaluate combinations:
- ESO + Vault → Most flexible, K8s Secret intermediate
- CSI Driver + Vault → No intermediate, more complex
- ESO + AWS Secrets Manager → Simple for AWS-native
- ESO + multiple backends → Multi-cloud flexibility

### 2. Asya-specific interface design

**Option A: Extend AsyncActor CRD**
```yaml
spec:
  secrets:
    - name: OPENAI_API_KEY
      externalSecretRef:
        name: openai-credentials
        key: api_key
```
Requires ExternalSecret to exist separately.

**Option B: New AsyaSecret CRD**
```yaml
apiVersion: asya.dev/v1alpha1
kind: AsyaSecret
metadata:
  name: openai-credentials
spec:
  provider: vault
  path: secret/data/openai
  keys:
    - remoteKey: api_key
      localName: OPENAI_API_KEY
---
# Actor references it
spec:
  secretRefs:
    - openai-credentials
```
Operator creates ExternalSecret under the hood.

**Option C: Inline provider reference**
```yaml
spec:
  secrets:
    - name: OPENAI_API_KEY
      vault:
        path: secret/data/openai
        key: api_key
    - name: AWS_SECRET
      awsSecretsManager:
        secretName: prod/myapp
        key: password
```
Operator generates ExternalSecret from inline config.

### 3. Secret rotation handling

- How to handle secret rotation without pod restart?
- ESO supports refresh intervals
- CSI driver can remount
- Sidecar pattern: Vault Agent handles rotation

### 4. Multi-tenancy considerations

- Each namespace may have different secret providers
- RBAC: Who can reference which secrets?
- Audit: Track which actors access which secrets

### 5. Local development story

- Developers need secrets too
- `asya dev` command with local secret injection?
- `.env` files for local, external providers for prod?

## Comparison Matrix

| Feature | ESO | CSI Driver | Vault Agent |
|---------|-----|------------|-------------|
| K8s Secret intermediate | ✅ Yes | ❌ Optional | ❌ No |
| Multi-provider | ✅ Many | 🟡 Few | ❌ Vault only |
| Secret rotation | ✅ Polling | ✅ Remount | ✅ Native |
| Complexity | 🟢 Low | 🟡 Medium | 🔴 High |
| CNCF status | ✅ Incubating | ✅ SIG project | ❌ HashiCorp |

## Research Deliverables

1. **Provider comparison** - ESO vs CSI vs Vault Agent
2. **Interface design doc** - AsyncActor secret reference syntax
3. **PoC implementation** - ESO integration with asya-operator
4. **Security review** - Threat model for secret flow
5. **Developer experience** - Local dev secret workflow

## Links

- External Secrets Operator: https://external-secrets.io/
- Secrets Store CSI Driver: https://secrets-store-csi-driver.sigs.k8s.io/
- Vault K8s integration: https://developer.hashicorp.com/vault/docs/platform/k8s
- SPIFFE/SPIRE: https://spiffe.io/


---
## Notes

## Initial Thoughts (from creation)

**Design philosophy:**
- Asya should NOT implement secret storage (that's solved)
- Asya SHOULD provide ergonomic interface to existing solutions
- "Batteries included" default (ESO) with escape hatches

**Why ESO is likely the "golden stack":**
- CNCF Incubating = community vetted, active maintenance
- Multi-provider = users bring their own secret store
- K8s-native = operators already understand CRDs
- The "K8s Secret intermediate" concern is often overblown:
  - Secrets in etcd can be encrypted at rest
  - ESO supports `refreshInterval` for rotation
  - Alternative (CSI) adds more operational complexity

**Asya operator integration points:**
1. **Reconcile AsyncActor** → Check for secret refs
2. **Create/validate ExternalSecret** → Ensure secrets exist before pod
3. **Inject secret mounts** → Add volume mounts to pod spec
4. **Watch for secret changes** → Trigger pod rollout if needed

**Secret reference design goals:**
- Simple for common case: `secretRef: my-secret`
- Flexible for complex: inline provider config
- Discoverable: `kubectl explain asyncactor.spec.secrets`

**Data scientist UX:**
```yaml
# They write this:
spec:
  handler: my_model.predict
  secrets:
    - OPENAI_API_KEY: vault/openai#key

# Operator creates ExternalSecret, K8s Secret, volume mounts
# Handler code just does: os.environ["OPENAI_API_KEY"]
```

**Edge cases to consider:**
- Secret doesn't exist yet → Actor should fail fast, clear error
- Secret rotated → How to signal handler to refresh?
- Multiple actors share secret → Single ExternalSecret, multiple refs
- Namespace isolation → Actor can only ref secrets in same namespace

**Synergy with other beads:**
- asya-an2 (HolmesGPT): "Why did actor fail?" → "Secret not found"
- asya-tix (CLI): `asya secrets list`, `asya secrets validate`


---
_Migrated from beads `asya-n93`_
