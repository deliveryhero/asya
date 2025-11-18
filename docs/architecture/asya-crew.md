# Asya Crew

System actors with reserved roles for framework-level tasks.

## Current Crew Actors

### happy-end

**Responsibilities**:
- Persist successful results to S3/MinIO
- Report success to gateway

**Queue**: `asya-happy-end` (automatically routed by sidecar)

**Configuration**:
```yaml
env:
- name: ASYA_STORAGE
  value: s3  # or minio
- name: ASYA_S3_BUCKET
  value: asya-results
- name: ASYA_S3_PREFIX
  value: completed/
- name: ASYA_GATEWAY_URL
  value: http://asya-gateway:80
```

**Flow**:
1. Receive envelope with final payload
2. Upload payload to S3: `s3://{bucket}/{prefix}/{envelope_id}.json`
3. Report success to gateway: `POST /envelopes/{id}/status`

### error-end

**Responsibilities**:
- Persist failed envelopes to S3/MinIO
- Report failure to gateway
- Future: Retry logic with exponential backoff

**Queue**: `asya-error-end` (automatically routed by sidecar)

**Configuration**:
```yaml
env:
- name: ASYA_STORAGE
  value: s3
- name: ASYA_S3_BUCKET
  value: asya-results
- name: ASYA_S3_PREFIX
  value: errors/
- name: ASYA_GATEWAY_URL
  value: http://asya-gateway:80
```

**Flow**:
1. Receive error envelope
2. Extract error details from envelope
3. Upload to S3: `s3://{bucket}/{prefix}/{envelope_id}.json`
4. Report failure to gateway: `POST /envelopes/{id}/status`

## Deployment

Crew actors deployed via Helm:

```bash
helm install asya-crew deploy/helm-charts/asya-crew/ \
  --set storage=s3 \
  --set s3Bucket=asya-results
```

**Namespace**: Same as other actors (e.g., `default`, `asya-poc`)

## Future Crew Actors

**Stateful fan-in**:
- Aggregate fan-out results
- Wait for all chunks to complete
- Merge results and continue pipeline

**Auto-retry**:
- Implement exponential backoff
- Retry failed envelopes
- Move to DLQ after max attempts

**Custom monitoring**:
- Track SLA violations
- Alert on error rates
- Generate reports
