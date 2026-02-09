Missing points:

- infrastructure, stability
    - observability (metrics per-actor)
    - flow graph in grafana
- timeouts
- error handling
- cli deployment
    - flow abstraction deployment at once

- agentic frameworks integration
    - python syntax for tools/agents
    - event streaming
    - gateway to comply with a2a
    - stateful fan-in actor
- control plane gateway API
    - register new mcp tools for existing actors
    - create new actors from code (???)
    - integration with kapp for asya flow

- binary protocol optimization
- docs
    - quickstart guide
    - comparisons pages
    - more real-world examples
    - initiate ards




---
quickstart/README.md work

    3. asya-2jb - Complete Prometheus monitoring section in quickstart
        - Depends on: Gateway section + Grafana dashboards
        - Deploy kube-prometheus-stack (Prometheus + Grafana)
        - Create ServiceMonitors for operator, gateway, actor sidecars
        - Import dashboards, port-forward Grafana
        - Add verification: call actors via MCP, view metrics in Grafana
    4. asya-a65 - Test Prometheus + Grafana setup in local Kind cluster
        - Depends on: Prometheus section complete
        - End-to-end validation of the quickstart
        - Test all 3 complexity levels (minimal → crew → gateway+monitoring)
        - Document issues/improvements
    5. asya-tb8 - Update observability docs to reference quickstart setup
        - Depends on: Testing complete
        - Link docs/architecture/observability.md to quickstart
        - Cross-reference Grafana dashboards
