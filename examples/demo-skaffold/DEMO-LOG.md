# Skaffold Demo Log

**Date**: 2026-03-22
**Cluster**: gke_foodsci-img-gen-dev-1407-1448_europe-west1_asya-demo
**kubectl context**: gke_foodsci-img-gen-dev-1407-1448_europe-west1_asya-demo
**Registry**: europe-west1-docker.pkg.dev/foodsci-img-gen-dev-1407-1448/asya-demo
**Asya version**: v0.5.8 (published charts from asya.sh/charts)

---

## Platform setup (asya-demo namespace)

Installed v0.5.8 charts individually (not via asya-playground umbrella):

```bash
# 1. Crossplane (Phase 1: providers only)
helm install asya-crossplane asya/asya-crossplane --version 0.5.8 -n asya-demo \
  --set providerConfigs.install=false \
  --set providers.gcp.enabled=true ...

# 2. Wait for GCP provider, enable ProviderConfigs
kubectl wait provider.pkg.crossplane.io/provider-gcp-pubsub --for=condition=Healthy
helm upgrade asya-crossplane --reuse-values --set providerConfigs.install=true

# 3. Crew
helm install asya-crew asya/asya-crew --version 0.5.8 -n asya-demo \
  --set image.tag=0.5.8 --set dlq-worker.enabled=false

# 4. Gateway (externalDatabase pointing to existing PostgreSQL)
helm install asya-gateway asya/asya-gateway --version 0.5.8 -n asya-demo \
  --set image.tag=0.5.8 \
  --set transports.pubsub.enabled=true \
  --set transports.pubsub.config.projectId=foodsci-img-gen-dev-1407-1448 \
  --set postgresql.enabled=false \
  --set externalDatabase.host=asya-gateway-postgresql \
  --set externalDatabase.existingSecret=asya-gateway-postgresql \
  --set externalDatabase.existingSecretKey=password \
  --set service.type=LoadBalancer --no-hooks
```

### Issues found during install

1. **asya-gateway-db secret**: The gateway chart references `<release>-db` secret
   for ASYA_DATABASE_URL but doesn't create it when `externalDatabase.existingSecret`
   is set. Had to create manually with the DSN.
2. **PG password mismatch**: The PostgreSQL PVC retains the old password from initdb.
   Had to `ALTER USER asya WITH PASSWORD '...'` to match the K8s secret.
3. **ProviderConfig ownership**: After uninstalling the playground umbrella chart,
   the `in-cluster` ProviderConfig retained the old helm release annotation.
   Had to `kubectl annotate` to fix ownership before helm upgrade.

### Final state

```
$ kubectl -n asya-demo get pods
NAME                                 READY   STATUS    RESTARTS   AGE
asya-gateway-api-688678ffc8-rg24n    1/1     Running   0          33s
asya-gateway-mesh-6dc8ffc8d4-wn4rj   1/1     Running   0          33s
asya-gateway-postgresql-0            1/1     Running   0          4d17h
x-sink-749bf87bdf-v6ptq              2/2     Running   0          4m23s
x-sump-6f6c58dd55-clddz              2/2     Running   0          4m23s

$ helm -n asya-demo list
NAME            CHART                 APP VERSION
asya-crossplane asya-crossplane-0.5.8 0.5.8
asya-crew       asya-crew-0.5.8       0.5.8
asya-gateway    asya-gateway-0.5.8    0.5.8
```

---

## Demo-skaffold namespace setup — step-by-step

These are the exact commands used. They should inform future `asya` CLI
commands (e.g. `asya ns init`, `asya build`, `asya deploy`).

### Step 1: Clean stale resources

```bash
kubectl -n $NS delete asyncactor --all
kubectl -n $NS delete deploy --all
helm --kube-context $CTX -n $NS uninstall asya-crew
```

### Step 2: Namespace prerequisites

```bash
# 2a. asya-runtime ConfigMap (Python runtime mounted in every actor pod)
kubectl -n asya-demo get cm asya-runtime -o json | \
  jq '.metadata = {name: "asya-runtime", namespace: "'$NS'"}' | \
  kubectl apply -f -

# 2b. gcp-keda-secret (KEDA TriggerAuthentication reads it locally)
kubectl -n keda get secret gcp-keda-secret -o json | \
  jq '.metadata = {name: "gcp-keda-secret", namespace: "'$NS'"}' | \
  kubectl apply -f -

# 2c. WI annotation on default KSA
kubectl annotate serviceaccount default -n $NS \
  iam.gke.io/gcp-service-account=asya-demo-actor@${PROJECT}.iam.gserviceaccount.com \
  --overwrite

# 2d. WI IAM binding (requires gcloud auth login with IAM permissions)
gcloud iam service-accounts add-iam-policy-binding \
  asya-demo-actor@${PROJECT}.iam.gserviceaccount.com \
  --role=roles/iam.workloadIdentityUser \
  --member="serviceAccount:${PROJECT}.svc.id.goog[${NS}/default]" \
  --condition=None --project=$PROJECT
```

### Step 3: Install crew (x-sink + x-sump)

```bash
helm install asya-crew asya/asya-crew --version 0.5.8 \
  --kube-context $CTX -n $NS \
  --set image.tag=0.5.8 \
  --set dlq-worker.enabled=false
```

### Step 4: Compile flow

```bash
cd examples/demo-skaffold
uv sync
uv run asya compile flows/pipeline.py --plot -v
```

Output: `compiled/pipeline/` — routers.py, flow.png, manifests/

### Step 5: Build + push images with Skaffold

```bash
skaffold build --default-repo=${REGISTRY} --kube-context=${CTX} \
  --file-output=build.json --push
```

`--file-output=build.json` captures image:tag pairs for each artifact.
`--push` pushes to Artifact Registry.

### Step 6: Update image tags from build output, recompile

**This is the manual step that `asya tag --from-build build.json` should automate.**

Currently: read build.json, update .asya/config.yaml build entries with
full registry+tag, then `asya compile` again.

```bash
# Extract tags from build.json
python3 -c "
import json
with open('build.json') as f:
    for b in json.load(f)['builds']:
        print(f\"{b['imageName']}={b['tag'].split('@')[0]}\")
"

# Update .asya/config.yaml build entries (manual edit)
# Then recompile:
uv run asya compile flows/pipeline.py --plot -v
```

### Step 7: Deploy compiled manifests

```bash
# asya k apply looks in .asya/manifests/ but compiler now outputs to compiled/
# Use kubectl kustomize directly:
kubectl kustomize compiled/pipeline/manifests/common | \
  kubectl apply --server-side -f -
```

**NOTE**: `asya k apply pipeline` fails because it looks in `.asya/manifests/pipeline`
but the compiler outputs to `compiled/pipeline/manifests`. This needs fixing in asya-lab.

### Step 8: Verify

```bash
kubectl -n $NS get asyncactors
kubectl -n $NS get pods
```

Wait ~2-3 minutes for Crossplane to create Pub/Sub topics + subscriptions.
KEDA needs ~5 minutes to start reading Stackdriver metrics.

### Step 9: Test end-to-end

```bash
gcloud pubsub topics publish projects/$PROJECT/topics/asya-$NS-start-pipeline \
  --message='{"id":"test-1","route":{"prev":[],"curr":"start-pipeline","next":[]},"headers":{},"payload":{"text":"This is a great and wonderful example of excellent writing"}}' \
  --project=$PROJECT
```

**Result**: Message flowed through the full pipeline:
```
start-pipeline -> actor-analyze -> actor-summarize -> actor-translate -> x-sink
```

x-sink received: `Prev:[start-pipeline actor-analyze actor-summarize actor-translate]`

### KEDA cold-start note

KEDA scales actors to 0 when queues are empty. New subscriptions take ~5 minutes
before Stackdriver metrics appear. During this window, KEDA can't detect backlog
and won't scale up. Workaround: pause KEDA scaling during initial testing:

```bash
kubectl -n $NS patch scaledobject <name> --type=merge \
  -p '{"metadata":{"annotations":{"autoscaling.keda.sh/paused":"true"}}}'
kubectl -n $NS scale deploy/<name> --replicas=1
```

---

## Pain points for CLI improvement

These are friction points from the manual walkthrough that should inform
future `asya` CLI commands.

| Pain point | Current workaround | Ideal CLI command |
|---|---|---|
| Namespace setup (copy ConfigMap, secrets, WI) | 4 separate kubectl commands | `asya ns init demo-skaffold --from asya-demo` |
| Image tags in config.yaml must match skaffold build output | Manual edit of .asya/config.yaml after each build | `asya tag --from-build build.json` (D5a) |
| `asya k apply` path mismatch | `kubectl kustomize compiled/.../common` | Fix `asya k apply` to check `compiled/` too |
| Compile-build-tag-recompile cycle | 4 commands, fragile ordering | `asya deploy pipeline` (compile + build + tag + apply) |
| KEDA cold-start (no metrics for ~5 min) | Pause ScaledObject + manual scale | `asya k scale pipeline --replicas=1` |
| Test message requires full envelope JSON | Manual gcloud pubsub topics publish | `asya test pipeline --payload '{"text":"hello"}'` |
| Skaffold uses wrong kube-context if not explicit | `--kube-context $CTX` on every command | Read from `.asya/config.yaml` contexts |

### The ideal workflow (future)

```bash
# 1. Setup
asya ns init demo-skaffold --from asya-demo

# 2. Develop
uv run python -c 'from flows.pipeline import pipeline; ...'  # local test

# 3. Compile
asya compile flows/pipeline.py --plot

# 4. Build (skaffold)
skaffold build --default-repo=${REGISTRY} --file-output=build.json --push

# 5. Tag (inject skaffold tags into compiled manifests)
asya tag --from-build build.json

# 6. Deploy
asya k apply pipeline

# 7. Test
asya test pipeline --payload '{"text":"hello world"}'
```

---

## Doc fixes applied (this session)

Updated `docs/setup/start-gcp-gke.md`:
- KEDA secret namespace: keda -> $NS (actor namespace)
- Local chart paths -> published charts (asya/asya-crossplane --version $ASYA_VERSION)
- Removed transport/compositionSelector from crew install (aint wozv)
- Removed sidecar.gcpCredsSecret (WI handles auth)
- Removed transport/compositionSelector from actor.yaml example
- Fixed provider wait name (provider-gcp-pubsub, not crossplane-provider-gcp-pubsub)

Updated `docs/setup/start-aws-eks.md`:
- Local chart paths -> published charts
- Added helm repo add asya

`docs/setup/start-quickstart.md`: Already correct, no changes needed.

## Bugs filed (previous session)

- **debt/mqd9**: Composition status pipeline never updates infrastructure.keda.ready
- **debt/msic**: Sidecar + runtime don't log error content before routing to x-sump
