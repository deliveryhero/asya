---
title: K8s Secrets support for AsyncActor (v0)
priority: 1 # high
assignee: Artem Yushkovskiy
tags:
  - worktree:.worktrees/agentic-security/wcnw.k8s-secrets-support-asyncactor-v0
  - branch:agentic-security/wcnw.k8s-secrets-support-asyncactor-v0
  - pr:282
dependencies:
  - 1fuy
---


Enable AsyncActor workloads to consume sensitive credentials (AI API tokens, DB passwords) via standard Kubernetes Secrets. This is the minimum viable secret injection story for v0 — no external vault required.

## Problem

Actors using LLM APIs (OpenAI, Anthropic, etc.) need API tokens available at runtime. Without a defined pattern, users resort to hardcoding or unsafe env var injection.

## Scope

### AsyncActor CRD extension
Add `spec.secretRefs` to the AsyncActor XRD:

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: openai-summarizer
spec:
  actor: openai-summarizer
  transport: sqs
  workload: ...
  secretRefs:
    - secretName: openai-creds
      keys:
        - key: api_key
          envVar: OPENAI_API_KEY
```

Actor code reads `os.environ["OPENAI_API_KEY"]` — no secret-fetching logic.

### Injector webhook (primary change)
When `spec.secretRefs` is present, the asya-injector webhook adds
`env[].valueFrom.secretKeyRef` entries to the **runtime** container
(where the Python actor code runs). The sidecar container is not affected.

No Crossplane composition change needed: the webhook reads the AsyncActor CR
at pod admission time and handles `secretRefs` entirely in the webhook layer.

### Documentation
- Quick-start example with an OpenAI actor using `secretRefs`
- Note that Secrets in etcd should be encrypted at rest (link to K8s docs)

## Out of Scope (post-v0)
- External secret stores (Vault, AWS Secrets Manager, ESO) — tracked in [1fdf]
- Secret rotation without pod restart
- Audit logging for secret access

## Acceptance Criteria
- AsyncActor with `secretRefs` correctly injects env vars into actor pods (runtime container)
- Actor Python code reads injected env vars transparently
- Unit tests for injector webhook secret injection logic
- Unit tests for secretRefs parsing from AsyncActor CR

---

## Implementation Plan

### Architecture

The injector webhook already reads the AsyncActor CR (`spec.secretRefs`) at pod admission
time via `getAsyncActorConfig → extractActorConfig`. It then calls `Inject(pod, actorConfig)`
which calls `modifyRuntimeContainer`. We extend this existing pipeline.

No Crossplane composition changes: secrets are injected at the Pod admission layer, not
at Deployment creation time. The Deployment template remains unchanged.

```
AsyncActor CR
  └── spec.secretRefs → extractActorConfig → ActorConfig.SecretRefs
                                                    │
                              modifyRuntimeContainer → runtime container
                                                         env[].valueFrom.secretKeyRef
```

### Task 1 — Add SecretRef types to ActorConfig

**File:** `src/asya-injector/internal/injection/config.go`

Add after `StateProxyMount`:

```go
// SecretRefKey maps a single Secret key to an env var name
type SecretRefKey struct {
	Key    string // key in the Secret
	EnvVar string // env var name in the container
}

// SecretRef references a Kubernetes Secret and which keys to inject
type SecretRef struct {
	SecretName string
	Keys       []SecretRefKey
}
```

Add to `ActorConfig`:

```go
// SecretRefs is the list of Secret references to inject into the runtime container
SecretRefs []SecretRef
```

Run: `make -C src/asya-injector test-unit`
Expected: PASS (no behaviour change yet)

Commit:
```bash
git add src/asya-injector/internal/injection/config.go
git commit -m "feat(injector): add SecretRef types to ActorConfig [wcnw]"
```

---

### Task 2 — Parse spec.secretRefs in extractActorConfig

**File:** `src/asya-injector/internal/webhook/asyncactor.go`

Add at the end of `extractActorConfig`, before `return config, nil`:

```go
// Extract secretRefs
secretRefsRaw, found, _ := unstructured.NestedSlice(spec, "secretRefs")
if found {
	for _, sr := range secretRefsRaw {
		srMap, ok := sr.(map[string]interface{})
		if !ok {
			continue
		}
		ref := injection.SecretRef{}
		ref.SecretName, _, _ = unstructured.NestedString(srMap, "secretName")
		if ref.SecretName == "" {
			continue
		}
		keysRaw, keysFound, _ := unstructured.NestedSlice(srMap, "keys")
		if keysFound {
			for _, k := range keysRaw {
				kMap, ok := k.(map[string]interface{})
				if !ok {
					continue
				}
				key := injection.SecretRefKey{}
				key.Key, _, _ = unstructured.NestedString(kMap, "key")
				key.EnvVar, _, _ = unstructured.NestedString(kMap, "envVar")
				if key.Key != "" && key.EnvVar != "" {
					ref.Keys = append(ref.Keys, key)
				}
			}
		}
		if len(ref.Keys) > 0 {
			config.SecretRefs = append(config.SecretRefs, ref)
		}
	}
}
```

Write failing test first in `src/asya-injector/internal/webhook/asyncactor_test.go`:

```go
func TestExtractActorConfig_SecretRefs(t *testing.T) {
	asyncActor := &unstructured.Unstructured{
		Object: map[string]interface{}{
			"spec": map[string]interface{}{
				"transport": "sqs",
				"region":    "us-east-1",
				"secretRefs": []interface{}{
					map[string]interface{}{
						"secretName": "openai-creds",
						"keys": []interface{}{
							map[string]interface{}{
								"key":    "api_key",
								"envVar": "OPENAI_API_KEY",
							},
						},
					},
				},
			},
			"status": map[string]interface{}{
				"conditions": []interface{}{
					map[string]interface{}{"type": "Ready", "status": "True"},
				},
			},
		},
	}

	config, err := extractActorConfig(asyncActor)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(config.SecretRefs) != 1 {
		t.Fatalf("expected 1 SecretRef, got %d", len(config.SecretRefs))
	}
	if config.SecretRefs[0].SecretName != "openai-creds" {
		t.Errorf("expected secretName 'openai-creds', got %q", config.SecretRefs[0].SecretName)
	}
	if len(config.SecretRefs[0].Keys) != 1 {
		t.Fatalf("expected 1 key, got %d", len(config.SecretRefs[0].Keys))
	}
	if config.SecretRefs[0].Keys[0].Key != "api_key" {
		t.Errorf("expected key 'api_key', got %q", config.SecretRefs[0].Keys[0].Key)
	}
	if config.SecretRefs[0].Keys[0].EnvVar != "OPENAI_API_KEY" {
		t.Errorf("expected envVar 'OPENAI_API_KEY', got %q", config.SecretRefs[0].Keys[0].EnvVar)
	}
}
```

Run failing: `make -C src/asya-injector test-unit`
Add parsing code. Run passing: `make -C src/asya-injector test-unit`

Commit:
```bash
git add src/asya-injector/internal/webhook/asyncactor.go \
        src/asya-injector/internal/webhook/asyncactor_test.go
git commit -m "feat(injector): parse spec.secretRefs from AsyncActor CR [wcnw]"
```

---

### Task 3 — Inject secretKeyRef env vars into runtime container

**File:** `src/asya-injector/internal/injection/inject.go`

In `modifyRuntimeContainer`, after the `appendEnvIfNotExists` calls and before `addRuntimeProbes`, add:

```go
// Inject secret key refs into runtime container
for _, sr := range actorConfig.SecretRefs {
	for _, k := range sr.Keys {
		runtime.Env = append(runtime.Env, corev1.EnvVar{
			Name: k.EnvVar,
			ValueFrom: &corev1.EnvVarSource{
				SecretKeyRef: &corev1.SecretKeySelector{
					LocalObjectReference: corev1.LocalObjectReference{
						Name: sr.SecretName,
					},
					Key: k.Key,
				},
			},
		})
	}
}
```

Write failing test first in `src/asya-injector/internal/injection/inject_test.go`:

```go
func TestInjector_Inject_SecretRefs(t *testing.T) {
	cfg := &config.Config{
		SidecarImage:           "ghcr.io/deliveryhero/asya-sidecar:test",
		RuntimeConfigMap:       "asya-runtime",
		SidecarImagePullPolicy: "IfNotPresent",
		SocketDir:              "/var/run/asya",
		RuntimeMountPath:       "/opt/asya/asya_runtime.py",
	}
	injector := NewInjector(cfg)

	pod := &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{Name: "test-pod", Namespace: "default"},
		Spec: corev1.PodSpec{
			Containers: []corev1.Container{
				{Name: "asya-runtime", Image: "my-app:v1"},
			},
		},
	}

	actorConfig := &ActorConfig{
		ActorName: "my-actor",
		Namespace: "default",
		Transport: "sqs",
		Region:    "us-east-1",
		SecretRefs: []SecretRef{
			{
				SecretName: "openai-creds",
				Keys: []SecretRefKey{
					{Key: "api_key", EnvVar: "OPENAI_API_KEY"},
					{Key: "org_id", EnvVar: "OPENAI_ORG_ID"},
				},
			},
		},
	}

	mutated, err := injector.Inject(pod, actorConfig)
	if err != nil {
		t.Fatalf("Inject failed: %v", err)
	}

	// Find runtime container
	var runtime *corev1.Container
	for i := range mutated.Spec.Containers {
		if mutated.Spec.Containers[i].Name == "asya-runtime" {
			runtime = &mutated.Spec.Containers[i]
			break
		}
	}
	if runtime == nil {
		t.Fatal("runtime container not found")
	}

	// Verify secretKeyRef env vars are in runtime container
	secretEnvs := map[string]*corev1.SecretKeySelector{}
	for _, e := range runtime.Env {
		if e.ValueFrom != nil && e.ValueFrom.SecretKeyRef != nil {
			secretEnvs[e.Name] = e.ValueFrom.SecretKeyRef
		}
	}

	if sel, ok := secretEnvs["OPENAI_API_KEY"]; !ok {
		t.Error("OPENAI_API_KEY not injected into runtime container")
	} else {
		if sel.Name != "openai-creds" {
			t.Errorf("expected secret name 'openai-creds', got %q", sel.Name)
		}
		if sel.Key != "api_key" {
			t.Errorf("expected key 'api_key', got %q", sel.Key)
		}
	}

	if sel, ok := secretEnvs["OPENAI_ORG_ID"]; !ok {
		t.Error("OPENAI_ORG_ID not injected into runtime container")
	} else {
		if sel.Key != "org_id" {
			t.Errorf("expected key 'org_id', got %q", sel.Key)
		}
	}

	// Verify sidecar does NOT get secret env vars
	var sidecar *corev1.Container
	for i := range mutated.Spec.Containers {
		if mutated.Spec.Containers[i].Name == "asya-sidecar" {
			sidecar = &mutated.Spec.Containers[i]
			break
		}
	}
	for _, e := range sidecar.Env {
		if e.ValueFrom != nil && e.ValueFrom.SecretKeyRef != nil {
			t.Errorf("sidecar should not get secretKeyRef env vars, got: %s", e.Name)
		}
	}
}
```

Run failing: `make -C src/asya-injector test-unit`
Add injection code. Run passing: `make -C src/asya-injector test-unit`

Commit:
```bash
git add src/asya-injector/internal/injection/inject.go \
        src/asya-injector/internal/injection/inject_test.go
git commit -m "feat(injector): inject secretKeyRef env vars into runtime container [wcnw]"
```

---

### Task 4 — Add spec.secretRefs to XRD schema

**File:** `deploy/helm-charts/asya-crossplane/templates/xrd-asyncactor.yaml`

Add after the `stateProxy` block (line ~211, before `status:`) inside `spec.properties`:

```yaml
                secretRefs:
                  type: array
                  description: Secret references to inject as env vars into the actor runtime container
                  items:
                    type: object
                    required:
                      - secretName
                      - keys
                    properties:
                      secretName:
                        type: string
                        description: Name of the Kubernetes Secret in the same namespace
                        minLength: 1
                      keys:
                        type: array
                        minItems: 1
                        items:
                          type: object
                          required:
                            - key
                            - envVar
                          properties:
                            key:
                              type: string
                              description: Key within the Secret
                              minLength: 1
                            envVar:
                              type: string
                              description: Environment variable name to inject into the runtime container
                              minLength: 1
```

No Crossplane composition change needed — secretRefs are consumed entirely
by the injector webhook at pod admission time.

Commit:
```bash
git add deploy/helm-charts/asya-crossplane/templates/xrd-asyncactor.yaml
git commit -m "feat(xrd): add spec.secretRefs schema to AsyncActor XRD [wcnw]"
```

---

### Task 5 — Run all unit tests and lint

```bash
make -C src/asya-injector test-unit
make lint
```

Fix any lint issues, then:

```bash
git add -p
git commit -m "chore(injector): lint fixes [wcnw]"
```
