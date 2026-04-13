---
title: "Design: S3 key lookup for GetTask history/artifacts"
status: merged
priority: 2
assignee: Artem Yushkovskiy
parent: emmc5
tags:
  - worktree:.worktrees/a2a-protocol-compliance-gateway/nqv1.design-s3-key-lookup-gettask-history-artifacts
  - branch:a2a-protocol-compliance-gateway/nqv1.design-s3-key-lookup-gettask-history-artifacts
  - pr:265
---

The checkpointer writes envelope data to S3 with key pattern {prefix}/{timestamp}/{actor}/{id}.json. The gateway DB doesn't currently store the S3 key or enough info to reconstruct it (timestamp, terminal actor name). Need to design: (1) whether to store S3 key in tasks table on final status report, (2) or use S3 prefix listing to find by task ID, (3) or change the checkpointer key pattern. Prerequisite for T16 (tgfp) GetTask history and artifacts from S3.
