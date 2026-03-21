# Comparisons

How does 🎭 Asya compare to other tools in the ecosystem? Each page provides honest,
factual comparisons with real code examples.

## By Category

| Category | Tools compared | Key question |
|----------|---------------|--------------|
| [Workflow Orchestrators](as-workflow-orchestrator.md) | Temporal, Argo, Airflow, Prefect, Dagster | "Why not use an orchestrator?" |
| [Actor Frameworks](as-actor-framework.md) | Erlang/OTP, Akka/Pekko, Orleans, Dapr | "How is Asya different from traditional actors?" |
| [Agentic Frameworks](as-agentic-framework.md) | LangGraph, CrewAI, Google ADK, AutoGen, KAgent | "Why not run agents in-process?" |
| [ML Pipeline Tools](as-ml-pipeline-tool.md) | KFP, Flyte, Metaflow, ZenML | "These also do ML pipelines on K8s" |
| [Stream Processing](as-stream-processing.md) | Flink, Kafka Streams, Spark Streaming | "Asya uses queues too — how is it different?" |
| [AI/ML Serving](as-ai-serving.md) | KServe, KAITO, KubeAI, vLLM, LLM-d | "Asya integrates with, not replaces" |
| [K8s Job Schedulers](as-k8s-scheduler.md) | Kueue, Run.ai, Volcano | "These schedule GPU jobs — Asya orchestrates pipelines" |

## In-Depth (1:1)

| Comparison | Why it matters |
|------------|---------------|
| [vs Temporal](vs-temporal.md) | Strongest workflow competitor — centralized replay vs decentralized queues |
| [vs Dapr](vs-dapr.md) | Closest sidecar model — both inject sidecars, different philosophy |
| [vs LangGraph](vs-langgraph.md) | Most popular agentic framework — in-process graph vs distributed mesh |
| [vs Google ADK](vs-google-adk.md) | Google's agentic SDK — output_key pattern vs envelope routing |
| [vs KAgent](vs-kagent.md) | CNCF Sandbox, K8s-native agents — agent CRDs vs actor CRDs |
| [vs Ray Serve](vs-ray-serve.md) | ML serving + distributed compute — Ray cluster vs K8s-native mesh |
| [vs Kubeflow Pipelines](vs-kubeflow-pipelines.md) | Established ML pipeline tool — Argo DAGs vs actor mesh |
