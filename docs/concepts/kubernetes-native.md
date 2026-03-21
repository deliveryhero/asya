# Kubernetes Native

Asya is not a layer on top of Kubernetes — it is Kubernetes. Actors are Custom
Resources, managed by standard Kubernetes tooling. No proprietary CLI, no
separate control plane, no new API to learn.

## AsyncActor is a CRD

Every actor is an `AsyncActor` Custom Resource. This means:

- **kubectl** — `kubectl get asyncactors`, `kubectl describe`, `kubectl delete`
- **Helm** — deploy actors as Helm releases with values overrides
- **GitOps** — ArgoCD and Flux reconcile actor manifests like any other resource
- **RBAC** — standard Kubernetes roles control who can create or modify actors
- **Namespaces** — actors are namespaced resources with standard isolation

## Crossplane Compositions render pods

Asya uses Crossplane Compositions to transform an `AsyncActor` spec into a full
Kubernetes Deployment. The composition renders:

- The runtime container with the handler ConfigMap
- The asya-sidecar container for envelope routing
- Optional state proxy sidecar
- Volumes, secrets, and environment variables

No operator webhook mutates pods after creation. The composition is the single
source of truth for the pod spec.

## Standard Kubernetes building blocks

| Concern | Kubernetes primitive |
|---------|---------------------|
| Workloads | Deployments (not StatefulSets) |
| Autoscaling | KEDA ScaledObjects |
| Configuration | ConfigMaps, Secrets |
| Networking | Services, Ingress |
| Resource management | Crossplane XRDs + Compositions |

## Runs anywhere

Because Asya uses standard Kubernetes primitives, it runs on any conformant
cluster:

- Local development: Kind, Minikube, k3s
- Cloud: EKS, GKE, AKS
- On-premises: kubeadm, Rancher, OpenShift

## Further reading

- [AsyncActor CRD specification](../reference/specs/asyncactor-crd.md) — full
  field reference
- [Crossplane component reference](../reference/components/core-crossplane.md)
  — composition architecture, XRD schema
- [Quickstart](../setup/start-quickstart.md) — deploy your first actor on a
  local cluster
