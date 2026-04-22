In order for pods in `atem` namespaces could run on aimc_* images from ECR, we need to create a static image pull secret:

```
TOKEN=$(aws-test ecr get-login-password --region eu-central-1)
ktest create secret docker-registry ecr-pull-secret \
    --namespace=atem \
    --docker-server=380754419530.dkr.ecr.eu-central-1.amazonaws.com \
    --docker-username=AWS \
    --docker-password="$TOKEN"
```
