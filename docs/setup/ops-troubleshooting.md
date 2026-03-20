# Troubleshooting

Common issues and solutions.

## Actor Not Starting

**Symptoms**: Pods pending or crashing

**Check**:
```bash
kubectl describe pod <pod-name>
kubectl logs <pod-name>
```

**Common causes**:

- Missing image
- Wrong ASYA_HANDLER value
- Missing dependencies
- Resource limits too low

## Queue Not Created

**Symptoms**: Sidecar connection errors

**Check**:
```bash
kubectl describe asyncactor <actor-name>
kubectl get sqsqueue <queue-name> -o yaml
kubectl logs -n crossplane-system -l pkg.crossplane.io/provider=provider-aws
```

**Common causes**:

- Missing IAM permissions for Crossplane AWS provider
- AWS provider not configured correctly
- Network issues accessing AWS API

## Actor Not Scaling

**Symptoms**: Pods stuck at 0 or not scaling up

**Check**:
```bash
kubectl get scaledobject <actor-name> -o yaml
kubectl describe scaledobject <actor-name>
kubectl get hpa
kubectl describe asyncactor <actor-name>
```

**Common causes**:

- KEDA not installed
- Wrong queueLength configuration
- IAM permissions missing for KEDA
- Crossplane composition not creating ScaledObject correctly

## Sidecar Connection Errors

**Symptoms**: `connection_error` in sidecar logs

**Check**:
```bash
kubectl logs deploy/<actor> -c asya-sidecar
```

**Common causes**:

- Wrong transport configuration
- Missing credentials
- Queue doesn't exist
- Network policy blocking

## Runtime Errors

**Symptoms**: `processing_error` in logs

**Check**:
```bash
kubectl logs deploy/<actor> -c asya-runtime
```

**Common causes**:

- Handler function not found
- Wrong `ASYA_HANDLER` path
- Missing Python dependencies
- OOM (check memory limits)

## Frequent OOM

**Symptoms**: `oom_error` or `cuda_oom_error`

**Solutions**:

- Increase memory limits
- Use a larger GPU machine
- Reduce batch size
- Profile memory usage

## Timeout Errors

**Symptoms**: `timeout_error` in logs

**Solutions**:

- Increase `ASYA_RESILIENCY_ACTOR_TIMEOUT`
- Optimize handler performance
- Add timeout warning in handler

## Gateway Not Responding

**Symptoms**: HTTP 500 errors, timeouts

**Check**:
```bash
kubectl logs deploy/asya-gateway
kubectl describe pod <gateway-pod>
```

**Common causes**:

- PostgreSQL connection failed
- Missing environment variables
- Tool configuration errors

## For More Help

- Check [Architecture Documentation](../architecture/README.md)
- Review logs with `kubectl logs`
- Describe resources with `kubectl describe`
