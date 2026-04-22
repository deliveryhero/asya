# ECR Image Pull Access (aimc-test cluster)

## TL;DR

No `imagePullSecret` or IRSA needed for ECR pulls. The node instance role
already has `AmazonEC2ContainerRegistryReadOnly`.

## Details

Verified 2026-04-22:

- Node instance profile: `aimc-gpu-l4-blue-node-group-*`
- Attached policy: `arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly`
- This grants all pods on the cluster pull access to all ECR repos in account
  `380754419530` (eu-central-1)

The `ecr-pull-secret` approach from earlier was unnecessary. If a pod gets
`ErrImagePull` from this ECR, the issue is the image/tag not existing, not auth.

## Verify an image exists

```bash
aws --profile aimc-test ecr describe-images \
  --repository-name aimc_model_pasd \
  --image-ids imageTag=0.5.0 \
  --region eu-central-1
```

## When IRSA would be needed

IRSA (IAM Roles for Service Accounts) is needed when a pod needs AWS API
access beyond what the node role provides, e.g.:

- S3 read/write (datasets, checkpoints, TFEvents)
- ECR push (building + publishing images)
- Cross-account ECR pull
- SQS/SNS (Asya transport)

To set up IRSA for a service account:

```bash
# 1. Create IAM role with trust policy for the OIDC provider
#    (Terraform/Pulumi preferred, manual steps below)

# 2. Annotate the service account
kubectl annotate sa default -n atem \
  eks.amazonaws.com/role-arn=arn:aws:iam::380754419530:role/<role-name>

# 3. Restart pods to pick up the new credentials
kubectl rollout restart deployment/workbench -n atem
```

Pods using IRSA get temporary credentials via the EKS OIDC provider —
no static secrets, no rotation needed.
