# Asya🎭 Examples

Examples and reference deployments for Asya🎭.

> **See also:** [Actor Examples Guide](../docs/guides/examples-actors.md) for detailed explanations

## Quick Start

**Recommended:** Use E2E deployment for local testing:
```bash
cd ../testing/e2e
make up
```

## Actor Examples (`asyas/`)

AsyncActor CRD examples demonstrating progressive configurations:

| File | Description |
|------|-------------|
| simple-actor.yaml | Minimal actor with RabbitMQ |
| no-scaling-actor.yaml | Fixed replicas without autoscaling |
| advanced-scaling-actor.yaml | Advanced KEDA scaling with formulas |
| gpu-actor.yaml | GPU actor for AI inference |
| fully-configured-actor.yaml | All runtime environment variables |
| multi-container-actor.yaml | Redis caching with multiple containers |
| custom-sidecar-actor.yaml | Custom sidecar configuration |
| custom-python-actor.yaml | Custom Python executable path |
| pipeline-preprocess.yaml | Multi-actor pipeline: preprocessing stage |
| pipeline-inference.yaml | Multi-actor pipeline: inference stage |
| pipeline-postprocess.yaml | Multi-actor pipeline: postprocessing stage |

**Detailed documentation:** See [asyas/README.md](asyas/README.md)

Deploy:
```bash
kubectl apply -f asyas/simple-actor.yaml
```

**Recommended for local development:** See [../docs/install/local-kind.md](../docs/install/local-kind.md) for full stack deployment with Kind cluster.

## Using Examples

**Copy and modify:**
```bash
cp asyas/simple-actor.yaml my-actor.yaml
vim my-actor.yaml
kubectl apply -f my-actor.yaml
```

**Run automated tests:**
```bash
./run-all-tests.sh  # Deploy + test + cleanup
```
