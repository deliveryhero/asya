---
title: "Enable flow compilation for async actors"
priority: 2 # medium
type: task
---


see .pre-commit-hooks/compile-flows.sh:
```sh
    # TODO: uncomment react_ once asya-cx34 is done
    [[ "$flow_name" == react_* ]] && continue
    # TODO: uncomment fanout_ once fan-out codegen is done (1fr7i0)
    [[ "$flow_name" == fanout_* ]] && continue
```

Once flow is able to process async generators and other async features, uncomment this.
