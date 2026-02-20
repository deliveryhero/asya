---
title: "Update 'When to Use Asya🎭' section in README"
status: open
priority: 2 # medium
type: task
---


Update the 'When to Use Asya🎭' section in the main README to better reflect verified use-cases.

**Current Issues:**
- README may contain unverified claims about what Asya is NOT ideal for (streaming use-cases, training jobs)
- These claims need validation or removal

**What Asya IS Ideal For (emphasize these):**

1. **AI use-cases with heavy processing steps:**
   - Long-running API calls
   - Image generation/processing
   - Video generation/processing
   - Other compute-intensive AI operations

2. **Complex workflows demanding distributed features:**
   - **Scalability**: Event-driven autoscaling with KEDA (scale-to-zero)
   - **Durability**: Persistent state through durable execution (envelope-based routing)
   - **Observability**: Built-in metrics and envelope tracking
   - **Decoupled Architecture**: Clear separation between data scientists (write handlers) and platform engineers (manage infrastructure)
   - **Event-Driven Workflows**: Async-native design with message passing

**Acceptance Criteria:**
- Remove or qualify unverified claims about streaming/training unsuitability
- Clearly articulate the strengths listed above
- Maintain professional tone consistent with rest of README
- Keep section concise and scannable


---
_Migrated from beads `asya-0q2`_
