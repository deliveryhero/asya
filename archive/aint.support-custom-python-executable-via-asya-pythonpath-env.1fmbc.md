---
title: Support custom Python executable via ASYA_PYTHONPATH env var
status: merged
priority: 3
parent: h0mji
tags:
  - type:feature
---

Allow users to specify a custom Python executable path by setting ASYA_PYTHONPATH (or detecting PYTHONPATH) as an env var on the asya-runtime container. When the asya-injector webhook sees this variable, it should use its value as the Python binary path in the sidecar command that launches the runtime. This replaces the old workload.pythonExecutable field from asya-operator with a more natural env-var-based approach.


---
**Close reason**: PR #152 implements ASYA_PYTHONPATH env var support in the injector


---
_Migrated from beads `asya-8y5`_
