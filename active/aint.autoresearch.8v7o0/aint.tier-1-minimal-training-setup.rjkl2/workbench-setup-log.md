# Workbench Setup Log

## 2026-04-17: Initial deployment

### 1. GCP Service Account (Vertex AI)

```bash
gcloud iam service-accounts create asya-workbench \
  --project=<GCP_PROJECT> \
  --display-name="Asya Workbench (Vertex AI)"

gcloud projects add-iam-policy-binding <GCP_PROJECT> \
  --member="serviceAccount:asya-workbench@<GCP_PROJECT>.iam.gserviceaccount.com" \
  --role="roles/aiplatform.user"

# BigQuery cross-project read access (data in prod project)
gcloud projects add-iam-policy-binding <GCP_PROD_PROJECT> \
  --member="serviceAccount:asya-workbench@<GCP_PROJECT>.iam.gserviceaccount.com" \
  --role="roles/bigquery.dataViewer" \
  --condition="expression=resource.name.startsWith('projects/<GCP_PROD_PROJECT>/datasets/aimc_tracking'),title=aimc-tracking-only"

gcloud projects add-iam-policy-binding <GCP_PROJECT> \
  --member="serviceAccount:asya-workbench@<GCP_PROJECT>.iam.gserviceaccount.com" \
  --role="roles/bigquery.jobUser"

# Download key and create K8s secret
gcloud iam service-accounts keys create /tmp/workbench-sa-key.json \
  --iam-account=asya-workbench@<GCP_PROJECT>.iam.gserviceaccount.com

ktest create secret generic gcp-vertex-ai-key -n atem \
  --from-file=key.json=/tmp/workbench-sa-key.json
rm /tmp/workbench-sa-key.json
```

### 2. Deploy manifests

```bash
ktest apply -f manifests/workbench-rbac.yaml
ktest apply -f manifests/workbench-pvcs.yaml
ktest apply -f manifests/workbench-deployment.yaml
```

Pod triggered autoscale (12->13 CPU worker nodes), running after ~2 min.

### 3. SSH setup in pod

sshd and authorized_keys are ephemeral (not on PVC). Must re-run after
pod restart until we bake this into the image or init script.

```bash
ktest exec -n atem deploy/workbench -- bash -c '
apt-get update -qq && apt-get install -y -qq openssh-server netcat-openbsd > /dev/null 2>&1
mkdir -p /run/sshd /home/vscode/.ssh
chmod 700 /home/vscode/.ssh
ssh-keygen -A 2>/dev/null
sed -i "s/#PermitRootLogin.*/PermitRootLogin no/" /etc/ssh/sshd_config
sed -i "s/#PasswordAuthentication.*/PasswordAuthentication no/" /etc/ssh/sshd_config
sed -i "s/#PubkeyAuthentication.*/PubkeyAuthentication yes/" /etc/ssh/sshd_config
echo "<YOUR_SSH_PUBLIC_KEY>" >> /home/vscode/.ssh/authorized_keys
chmod 600 /home/vscode/.ssh/authorized_keys
chown -R vscode:vscode /home/vscode/.ssh
/usr/sbin/sshd
'
```

### 4. Local SSH config

Added to `~/.ssh/google_compute_config`:

```
Host eks-workbench
  User vscode
  IdentityFile ~/.ssh/id_ed25519
  StrictHostKeyChecking no
  UserKnownHostsFile /dev/null
  ProxyCommand kubectl --kubeconfig <KUBECONFIG_PATH> exec -n atem deploy/workbench -i -- nc localhost 22
```

Tested: `ssh eks-workbench` works. No port-forward needed — uses kubectl
exec as tunnel, survives laptop sleep.

### Notes

- StorageClass is `gp2` (no gp3 on this cluster)
- Pod uses `default` SA which has `asya-actor` Pod Identity (SQS, S3, SecretsManager)
- devcontainer image `vscode` user is uid 1000, PVC at `/home/dev` is owned by root
- `/home/vscode` is ephemeral (container layer), `/home/dev` and `/storage` are PVCs

### Known Issues

- sshd + authorized_keys lost on pod restart (ephemeral, not on PVC)
- `roles/aiplatform.modelGardenUser` does not exist — `aiplatform.user` is sufficient
