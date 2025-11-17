# Asya🎭 Plans & Roadmap

This directory contains planning documents, technical comparisons, and roadmap items that will eventually migrate to GitHub issues.

## Directory Structure

```
plans/
├── README.md                               # This file
├── asya-deployment-health-tracking.md      # AsyaDeployment CRD design
├── asyncactor-binding-mode-design.md       # AsyncActor binding mode design
├── integrations.md                         # Integration plans
└── transport/                              # Transport layer plans
    └── keda-transport-comparison.md        # KEDA-supported transport analysis
```

## Document Types

### Technical Comparisons
In-depth analysis of technology choices, comparing options across multiple dimensions. These inform implementation decisions and roadmap priorities.

**Example**: `transport/keda-transport-comparison.md`

### Roadmap Items
Feature proposals and enhancement plans that will become GitHub issues once reviewed and approved.

### Architecture Decisions
High-level design documents for significant architectural changes.

## Migration to GitHub Issues

Documents in this directory represent **pre-issue planning**. Once a plan is:
1. Reviewed by maintainers
2. Approved for implementation
3. Broken down into actionable tasks

...it should be:
- Converted to GitHub issue(s)
- Tagged appropriately (`enhancement`, `research`, etc.)
- Added to project milestones
- Cross-referenced back to this plan document

## Contributing

When creating new plan documents:
- Use descriptive filenames (e.g., `feature-name-comparison.md`, `architecture-decision-record.md`)
- Include a **Status** section (Draft, Under Review, Approved, Migrated to Issue #XXX)
- Follow the structure: Overview → Analysis → Recommendations → Next Steps
- Update this README with new document categories as needed

## Current Focus Areas

- **Deployment Health**: AsyaDeployment CRD for namespace-local health tracking and crew validation
- **Binding Mode**: AsyncActor integration with third-party controllers (KAITO, KServe, KubeRay)
- **Transports**: Expanding beyond RabbitMQ/SQS to support NATS, Redis Streams, Kafka
