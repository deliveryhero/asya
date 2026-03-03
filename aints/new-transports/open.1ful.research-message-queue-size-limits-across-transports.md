---
title: "Research: Message queue size limits across transports"
priority: 2 # medium
tags:
  - beads:needs-spec
---




Research and document maximum message sizes for all supported and potential transports:
- SQS: 1,048,576 bytes (1 MiB) - confirmed
- Google Pub/Sub
- Kafka
- NATS Streaming
- Redis Streams
- RabbitMQ

Document findings in a table format. Update RFC with correct limits.


---
## Notes

## Session Discussion Takeaways (2026-01-28)

- SQS max is 1 MiB (not 256KB as previously documented in RFC)
- This significantly changes the architecture: most conversations fit without compression
- With binary protocol (~40-60% smaller), effective capacity is ~2.5 MiB equivalent
- Size analysis with binary:
  - Short (1-10 turns): ~3-12KB ✓
  - Medium (10-50 turns): ~12-60KB ✓
  - Long (50-200 turns): ~60-240KB ✓
  - Very long (200+): ~240KB+ (still fits for most cases)
- Only extreme cases (500+ turns) would hit limits
- This makes message-truth viable as default strategy


---
_Migrated from beads `asya-o42`_
