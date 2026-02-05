# Shared Docker Compose Configuration

Reusable Docker Compose files for integration testing with maximal configuration reuse.

## Directory Structure

```
testing/
├── shared/compose/                    # Shared infrastructure and 🎭 components
│   ├── rabbitmq.yml                   # RabbitMQ message transport
│   ├── sqs.yml                        # LocalStack SQS transport
│   ├── minio.yml                      # MinIO object storage
│   ├── postgres.yml                   # PostgreSQL + migrations
│   ├── asya/                          # 🎭 components
│   │   ├── gateway.yml                # MCP gateway service
│   │   ├── testing-actors.yml         # Test actor workloads
│   │   └── crew-actors.yml            # System actors (happy-end, error-end)
│   └── envs/                          # Environment files
│       ├── .env.tester                # Tester service config
│       ├── .env.rabbitmq              # RabbitMQ connection config
│       ├── .env.sqs                   # SQS connection config
│       └── .env.minio                 # MinIO storage config
│
└── integration/{test-suite}/
    ├── compose/                       # Local service definitions
    │   └── tester.yml                 # Tester service (extended by profiles)
    └── profiles/                      # Test profiles (assemblies)
        ├── .env.sqs-s3                # Profile variables: ASYA_TRANSPORT=sqs, ASYA_STORAGE=s3
        ├── .env.rabbitmq-minio        # Profile variables: ASYA_TRANSPORT=rabbitmq, ASYA_STORAGE=minio
        ├── sqs-s3.yml                 # Profile: SQS + S3 + tester
        └── rabbitmq-minio.yml         # Profile: RabbitMQ + MinIO + tester
```

## How It Works

### Profile Assembly Pattern

Profiles combine shared infrastructure, 🎭 components, and local services:

```yaml
# profiles/sqs-s3.yml
include:
  # Infrastructure (static)
  - path: ../../../shared/compose/sqs.yml
  - path: ../../../shared/compose/s3.yml
  - path: ../../../shared/compose/postgres.yml

  # Asya🎭 components (with variable substitution)
  - path: ../../../shared/compose/asya/gateway.yml
    env_file: .env.sqs-s3  # Provides ASYA_TRANSPORT=sqs, ASYA_STORAGE=s3

services:
  tester:
    extends:  # Reuse service definition without duplication
      file: ../compose/tester.yml
      service: tester
    depends_on:  # Profile-specific dependencies
      sqs-setup:
        condition: service_completed_successfully
      gateway:
        condition: service_healthy
```

### Variable Substitution Flow

1. Profile env file (`.env.sqs-s3`) defines: `ASYA_TRANSPORT=sqs`, `ASYA_STORAGE=s3`
2. Variables substitute in included files: `gateway.yml` line 14: `env_file: - ../envs/.env.${ASYA_TRANSPORT}` → `../envs/.env.sqs`
3. Tester service references same variables: `env_file: - ../envs/.env.${ASYA_TRANSPORT}`

### Key Docker Compose Features Used

- **`include:`** - Import compose files into profile
- **`env_file:` at include level** - Provide environment variables for substitution in included files
- **`extends:`** - Reuse service definitions without duplication (avoids conflicts)
- **`depends_on:`** - Profile-specific service dependencies

## Usage

```bash
# Run specific profile
cd testing/integration/gateway-actors
docker compose -f profiles/sqs-s3.yml up

# Via Makefile
make test-one MODE=payload TRANSPORT=sqs STORAGE=s3
```
