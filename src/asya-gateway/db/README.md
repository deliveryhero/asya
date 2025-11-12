# Asya🎭 Gateway Database Migrations

This directory contains database migrations for the Asya🎭 Gateway using [Sqitch](https://sqitch.org/).

## Prerequisites

Install Sqitch:

```bash
# macOS
brew install sqitch --with-postgres-support

# Ubuntu/Debian
apt-get install sqitch libdbd-pg-perl postgresql-client

# Or via Docker
docker pull sqitch/sqitch
```

## Migration Commands

### Deploy migrations

```bash
# Set database URL
export SQITCH_TARGET="db:pg://user:password@localhost:5432/asya_gateway"

# Deploy all pending migrations
cd src/asya-gateway/db
sqitch deploy

# Deploy specific migration
sqitch deploy 001_initial_schema
```

### Revert migrations

```bash
# Revert last migration
sqitch revert

# Revert to specific migration
sqitch revert 001_initial_schema

# Revert all migrations
sqitch revert --to @ROOT
```

### Verify migrations

```bash
# Verify current state
sqitch verify

# Verify specific migration
sqitch verify 001_initial_schema
```

### Check status

```bash
# Show deployment status
sqitch status

# Show deployment log
sqitch log
```

## Docker Usage

```bash
# Deploy using Docker
docker run --rm -it \
  -v $(pwd):/work \
  -w /work \
  sqitch/sqitch:latest-pg \
  deploy db:pg://user:password@host:5432/asya_gateway

# Or with environment variable
docker run --rm -it \
  -v $(pwd):/work \
  -w /work \
  -e SQITCH_TARGET="db:pg://user:password@host:5432/asya_gateway" \
  sqitch/sqitch:latest-pg \
  deploy
```

## Kubernetes/Helm

Migrations are automatically run via Helm hooks before gateway deployment. See:
- `deploy/helm-charts/asya-gateway/templates/db-migration-job.yaml`

## Schema Overview

### Tables

**envelopes**
- Stores envelope metadata and current state
- Primary table for envelope management
- Auto-updates `updated_at` on every change

**envelope_updates**
- Audit log of all envelope status changes
- Used for SSE streaming to provide full update history
- Automatically cleaned up when envelope is deleted (CASCADE)

### Indexes

- `idx_envelopes_status`: Fast filtering by envelope status
- `idx_envelopes_created_at`: Sorting by creation time
- `idx_envelopes_updated_at`: Finding recently updated envelopes
- `idx_envelopes_deadline`: Finding envelopes approaching timeout
- `idx_envelope_updates_envelope_id`: Fast lookup of updates per envelope
- `idx_envelope_updates_timestamp`: Time-ordered update stream

## Adding New Migrations

```bash
# Create new migration
cd src/asya-gateway/db
sqitch add <migration_name> -n "Description of migration"

# This creates three files:
# - deploy/<migration_name>.sql
# - revert/<migration_name>.sql
# - verify/<migration_name>.sql

# Edit the files, then deploy
sqitch deploy

# Test revert works
sqitch revert --to HEAD^
sqitch deploy
```

## Best Practices

1. **Always write revert scripts** - Every deploy must have a matching revert
2. **Test locally first** - Deploy and revert multiple times before committing
3. **Keep migrations atomic** - One logical change per migration
4. **Add verify scripts** - Ensure schema is in expected state
5. **Document breaking changes** - Add comments for schema changes that affect application code
6. **Never modify deployed migrations** - Create new migration to fix issues

## Connection String Format

```
db:pg://[username[:password]@][host][:port]/dbname[?params]
```

Examples:
```
db:pg://localhost/asya_gateway
db:pg://postgres:secret@localhost:5432/asya_gateway
db:pg://postgres@postgres.asya.svc.cluster.local:5432/asya_gateway?sslmode=require
```
