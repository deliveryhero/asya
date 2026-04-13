---
title: Complete Gateway section in quickstart README
status: merged
priority: 2
tags:
  - beads:epic:asya-ln2
---

The Gateway section (starting line 369) is marked TODO. Complete it with:
- Install gateway with Helm
- Update operator values for gateway integration
- Update crew values for gateway reporting
- Add CLI installation and usage examples (port-forward, list tools, call actors)
- Verify integration works

This unblocks the Prometheus section since metrics from gateway calls will be visible in Grafana.


---
**Close reason**: Closed


---
_Migrated from beads `asya-dqy`_
