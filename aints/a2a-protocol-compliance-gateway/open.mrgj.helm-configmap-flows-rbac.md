---
title: "Gateway Helm chart: mount flows ConfigMap + RBAC for flow exposure"
priority: 2 # medium
dependencies:
  - zaai
---

Update the gateway Helm chart to mount `gateway-flows` ConfigMap(s) as a
volume, and add RBAC resources for data scientists to patch the ConfigMap.

**Depends on**: `zaai` (ConfigMap toolstore implementation)
**ADR reference**: `adr.configmap-flow-registry.md` §RBAC, §Architecture

## Helm chart changes (deploy/helm-charts/asya-gateway)

### values.yaml additions

```yaml
flowsConfig:
  # Directory where flows ConfigMap(s) are mounted
  mountPath: /etc/asya/flows
  # Label selector for ConfigMaps to mount
  labelSelector:
    asya.sh/component: gateway
    asya.sh/config-type: flows
```

### deployment.yaml

Add volume + volumeMount for the flows ConfigMap:

```yaml
volumes:
  - name: gateway-flows
    projected:
      sources:
        - configMap:
            name: gateway-flows
            optional: true   # Gateway starts without flows (serves empty skills list)

volumeMounts:
  - name: gateway-flows
    mountPath: /etc/asya/flows
    readOnly: true
```

Set `ASYA_CONFIG_PATH` env var:

```yaml
env:
  - name: ASYA_CONFIG_PATH
    value: {{ .Values.flowsConfig.mountPath }}
```

### rbac.yaml (new template)

Create Role + RoleBinding for flow exposure:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: asya-flow-exposer
  namespace: {{ .Release.Namespace }}
rules:
  - apiGroups: [""]
    resources: ["configmaps"]
    resourceNames: ["gateway-flows"]
    verbs: ["get", "patch", "update"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: asya-flow-exposer
subjects:
  - kind: Group
    name: {{ .Values.flowsConfig.exposerGroup | default "asya-flow-exposers" }}
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: asya-flow-exposer
```

### gateway-flows-configmap.yaml (new template, optional)

Optionally include a starter empty ConfigMap:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: gateway-flows
  namespace: {{ .Release.Namespace }}
  labels:
    asya.sh/component: gateway
    asya.sh/config-type: flows
data:
  flows.yaml: |
    flows: []
```

## E2E test changes

The e2e test setup (`testing/e2e/`) currently registers tools via
`POST /mesh/expose`. After this change:

1. Create a `gateway-flows` ConfigMap in the Kind cluster with test flows
2. Remove all `POST /mesh/expose` calls from test setup scripts
3. Verify Agent Card reflects skills from ConfigMap within 5s of cluster startup

## Implementation estimate

~100 LOC YAML (Helm templates) + e2e test script updates.
