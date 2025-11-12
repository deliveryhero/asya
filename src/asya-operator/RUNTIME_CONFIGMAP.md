# Runtime ConfigMap Management

The operator automatically manages the `asya-runtime` ConfigMap containing `asya_runtime.py`.

## Overview

1. **At startup**: Operator loads `asya_runtime.py` from configured source
2. **Creates/updates**: The `asya-runtime` ConfigMap in target namespace
3. **Actors use**: ConfigMap injected as volume mount at `/opt/asya/asya_runtime.py`

## Configuration

### Local Development (Default)

```yaml
# values.yaml
runtime:
  source: local
  local:
    path: "../src/asya-runtime/asya_runtime.py"
  namespace: asya
```

### Production (GitHub Releases)

```yaml
# values.yaml
runtime:
  source: github
  github:
    repo: "deliveryhero/asya"
    version: "v1.0.0"
  namespace: asya
```

### Environment Variables

| Variable | Description |
|----------|-------------|
| `ASYA_RUNTIME_SOURCE` | `local` or `github` |
| `ASYA_RUNTIME_LOCAL_PATH` | Path to local file |
| `ASYA_RUNTIME_GITHUB_REPO` | GitHub repository |
| `ASYA_RUNTIME_VERSION` | Release version/tag |
| `ASYA_RUNTIME_NAMESPACE` | Namespace for ConfigMap |

## Benefits

- ✅ **Single source of truth**: No duplicate runtime code
- ✅ **Automatic updates**: Change source, restart operator → ConfigMap updated
- ✅ **Version control**: GitHub releases ensure correct runtime version
- ✅ **Local development**: Easy iteration with local file watching

## Troubleshooting

**Check operator logs**:
```bash
kubectl logs -n asya-system deploy/asya-operator | grep runtime
```

**Verify ConfigMap**:
```bash
kubectl get configmap asya-runtime -n asya
kubectl describe configmap asya-runtime -n asya
```

**Common issues**:
- **File not found**: Check `ASYA_RUNTIME_LOCAL_PATH` is correct
- **GitHub rate limit**: Use authenticated requests or wait
- **Wrong namespace**: Ensure `ASYA_RUNTIME_NAMESPACE` matches deployment namespace

## How It Works

**Local source**:
1. Operator reads file from local path
2. Creates ConfigMap with file contents
3. Watches file for changes (optional)

**GitHub source**:
1. Operator fetches from GitHub releases API
2. Downloads `asya_runtime.py` from release assets
3. Creates ConfigMap with fetched contents

**Actor injection**:
```yaml
# Operator automatically adds this to actor pods
volumes:
- name: asya-runtime
  configMap:
    name: asya-runtime
volumeMounts:
- name: asya-runtime
  mountPath: /opt/asya/asya_runtime.py
  subPath: asya_runtime.py
```

Actors run with:
```bash
python /opt/asya/asya_runtime.py
```

## See Also

- [Operator README](README.md) - Full operator documentation
- [Runtime README](../src/asya-runtime/README.md) - Runtime implementation
