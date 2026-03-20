# Run Asya

Deploy Asya on your cluster, configure transports, monitor and scale.

## Getting Started

Get a cluster running:

- **[Quickstart](start-quickstart.md)** — Local Kind cluster in 5 minutes
- **[AWS EKS](start-aws-eks.md)** — Production deployment on AWS
- **[GCP GKE](start-gcp-gke.md)** — Production deployment on GCP

## Guides

Configure and customize the platform:

- **[Helm Charts](guide-helm-charts.md)** — Chart configuration reference (gateway, crew, crossplane)
- **[Autoscaling](guide-autoscaling.md)** — KEDA configuration, scaling parameters, scenarios
- **[Actor Flavors](guide-actor-flavors.md)** — Create EnvironmentConfig resources for your org
- **[State Proxy](guide-state-proxy.md)** — Configure state proxy storage backends
- **[Pause/Resume](guide-pause-resume.md)** — Deploy x-pause/x-resume, configure S3 checkpoint
- **[Timeouts](guide-timeouts.md)** — Configure SLA, gateway backstop, transport timeouts
- **[Retries](guide-retries.md)** — Retry policies, error matching, DLQ configuration
- **[Gateway](guide-gateway.md)** — Deploy gateway modes, configure auth, register tools

## Operations

- **[Monitoring](ops-monitoring.md)** — Prometheus metrics, Grafana dashboards, alerting
- **[Troubleshooting](ops-troubleshooting.md)** — Symptom-to-solution checklist
- **[Upgrades](ops-upgrades.md)** — Version upgrade procedures, rollback
