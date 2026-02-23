---
title: Determine minimal Kubernetes version for Asya deployment
priority: 2 # medium
type: task
---



Research and document the minimal Kubernetes version required for Asya deployment.

Since KEDA is a critical component for autoscaling AsyncActors, the minimal K8s version is likely constrained by KEDA's requirements.

**Tasks:**
1. Check KEDA documentation for minimal K8s version support: https://keda.sh/docs/2.18/operate/cluster/
2. Verify kubebuilder/controller-runtime K8s API version requirements in asya-operator
3. **Test minimal K8s version deployment locally in Kind** (one-time verification in temporary directory)
   - Create Kind cluster with minimal supported version
   - Deploy asya-operator + basic AsyncActor
   - Verify KEDA autoscaling works
   - Clean up test environment
4. Document findings in CLAUDE.md or deployment documentation

**Expected outcome:**
Clear documentation of minimal K8s version (e.g., '1.24+') with rationale, verified through actual deployment testing.


---
_Migrated from beads `asya-rcb`_
