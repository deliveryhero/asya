README.md
    # tags
    # Key ideas (+link to concepts)
    # Links to docs/
    # dh logo
    # Overview for Data Scientists (short, teaser + link to quickstart)
    # Overview for Platform Engineers (short, teaser + link to quickstart)
    # Features (+link to concepts)
    # Architecture (+link to architecture/)
    # Getting Started (+link to install/ and quickstart/)
    # Contributing
    # License

docs/
    README.md
        # welcome to asya documentation
        # Overview of documentation structure (similar to this content)
        # Links to plan.md, concepts.md, architecture/, install/, operate/, quickstart-data_scientists.md, quickstart-platform_engineers.md
    motivation.md  # more detailed motivation than in /README.md
        # Problems:
            # pipeline logic (if/else, retries, error handling) mixed with business logic (data processing, AI inference) - e.g. @flow decorators
            # hard to scale different components differently
            # hard to deploy different components independently
            # hard to manage infra for data scientists
            # hard to operate at scale for platform engineers  
            # batch pipelines vs streaming, very different frameworks
            # (this decoupling is obvious for backend engineers, but very unnatural for data scientists)
        # What is Asya?
            # K8s-native async actor framework for orchestrating complex near-realtime AI pipelines at scale
            # decouples pipeline logic, infra logic, component logic
            # each component is an independent actor
            # each actor has sidecar (routing logic) + runtime (user code)
            # zero pip dependencies, radically simple interface for data scientists
            # actors communicate via async message passing (pluggable transports)
            # pipeline structure is not pre-defined in code, it is indirectly defined by each message (pipeline is data, not code)
            # built-in observability, reliability, extensibility, scalability
            # optional MCP HTTP gateway for easy integrations
        # Good fit:
            # Kubernetes-native deployments
            # near-realtime data processing pipelines
            # 10s-100s of different components with very different latency (from ms to minutes latency each)
                # including self-hosted AI components
                # including data processing components
                # including backend engineering components
            # bursty workloads with unpredictable traffic patterns
            # cost optimization through scale-to-zero for each component
            # GPU-intensive tasks requiring independent scaling
            # resilient processing with automatic retries
            # easy to use or integrate with other systems with configurable MCP Gateway
        # Not good fit:
            # Synchronous request-response APIs (use HTTP services instead)
            # Sub-second latency requirements (queue overhead adds ~100-500ms)
            # Simple single-step processing (overhead may not be worth it)
            # Stateful workflows requiring session affinity
        # Problems Asya solves:
            # AI orchestration that scales at constant maintenance cost
            # No single point of failure:
                # fully distributed architecture
                # no central orchestrator/DAG/flow
            # Separation of concerns:
                # pipeline structure -> pipeline is not python code with @flow decorators, it's part of each message (i.e. data, not code)
                # infra layer -> K8s-native, zero infra management for DS
                # component logic (business layer) -> fully controlled by DS
            # Scalability:
                # each component independently scalable based on their own message queue depth or HPA metrics
                # scale to zero (prevent wasted GPU)
            # Extensibility:
                # pluggable transports (SQS, RabbitMQ, etc)
                # Easy integration with other open-source toosl
            # Observability:
                # built-in observability for actors, sidecars, runtimes, operator, gateway
            # Reliability:
                # built-in retries, DLQs, error handling
            # Usability:
                # zero infrastructure management for DS
                # easy for platform engineers to operate at scale (K8s-native)
        # Problems Asya NOT solves:
            # does not provide pre-defined AI inference components (DS build their own runtimes) -> will integrate with those
            # not a CI/CD solution (needs one)
            # not a data storage solution (needs one)
            # not a data processing framework (DS build their own runtimes)
            # not a synchronous HTTP API framework (cannot beat HTTP LLM deployments with ms latency requirements due to large model startup time, queue overhead, etc)
            # not a managed service (bring your own K8s cluster)
        # Existing solutions:
            # Airflow, Prefect, Dagster, etc - monolithic orchestrators, not K8s-native, not async, hard to scale different components differently, hard to deploy different components independently
            # Kubeflow Pipelines - K8s-native, but monolithic orchestrator, not async, hard to scale different components differently, hard to deploy different components independently
            # Temporal.io - K8s-native, but monolithic orchestrator, not async, hard to scale different components differently, hard to deploy different components independently
            # Dapr - K8s-native, async actor framework, but not designed for data science workloads, lacks built-in observability/reliability/extensibility/scalability features needed for AI orchestration
            # Custom K8s-native solutions - require significant engineering effort to build and maintain, lack built-in features needed for AI orchestration
            # KAITO, LLM-d - easy deployment of LLMs via REST API - perfect integration point

    concepts.md
        # Actors
            # What is an Actor? (short)
            # stateless by design
            # Motivation: as alternative to monolithic pipeline
            # link to asya-actor.md
        # Sidecar
            # Responsibilities (message routing, transport management, observability, reliability)
            # link to asya-sidecar.md
        # Runtime
            # Responsibilities (user code execution, processing input messages, generating output messages)
            # How it works (receives messages from sidecar, processes them, sends results back to sidecar)
            # How it is deployed (as a separate container in the same pod as sidecar)
            # link to asya-runtime.md
        # Crew
            # Special actors for system-level tasks (e.g. logging, monitoring, message persistance, error handling)
            # link to asya-crew.md
        # Queue
            # Interface (send, receive, ack, nack)
            # Types of transports (SQS, RabbitMQ, etc)
            # link to transports/README.md
        # Envelope
            # vs Message (in Message Queue level - bytes), Envelope - json object with pre-defined fields
            # stateful (route 'current')
            # Example, required fields (id, route, payload), optional fields (headers)
        # Operator
            # Responsibilities (manages lifecycle of actors, monitors health, scales actors based on load)
            # How it works (watches K8s resources, creates/updates/deletes actor pods, collects metrics)
            # link to asya-operator.md
        # KEDA (autoscaling)
            # Benefits (automatic scaling, cost optimization, handling bursty workloads)
            # How Asya is integrated with KEDA (Asya creates KEDA ScaledObjects, which scales actor deployments based on message queue depth or custom metrics)
            # link to autoscaling.md
        # MCP Gateway (optional)
            # Responsibilities (exposes HTTP API for sending/receiving messages to/from actors)
            # How it works (receives HTTP requests, creates envelopes, sends to actors via sidecars, receieves HTTP status updates from sidecars)
            # link to asya-gateway.md
        # Observability (optional)
            # Built-in OTEL metrics (actor processing time, message throughput, error rates)
            # Integration with Prometheus/Grafana
            # link to observability.md

    architecture/
        asya-actor.md
            # What is an Actor? (stateless workload + input message box + sending messages)
            # As alternative to monolithic pipeline
            # Benefits of Actors (independent scaling, independent deployments, separation of concerns, resilience)
            # Diagram with components
            # Actor lifecycle, states (Napping, Running, ...)
            # Basic examples, link to examples/ with more yaml examples
            # Basic commands (kubectl get asyas, kubectl get hpa -w, etc)
            # Deployment with Helm charts
        asya-sidecar.md
            # Responsibilities (message routing, transport management, observability, reliability)
            # How it works (listens for incoming messages, routes to runtime, sends outgoing messages)
            # How it communicates with Runtime (protocols, transports)
            # How it is deployed (injected as a sidecar container in the same pod as runtime)
            # Error handling:
            # - If error in sidecar (nack message, is automatically sent to DLQ)
            # - If error in runtime (ack message, send to error-end)
            # - timeout (managed by sidecar, kills itself to restart whole pod)
            # Routing:
            # - just send to current actor (runtime must increment 'current' in route)
            # - when routes to happy-end (last message)
            # - when routes to error-end (error or timeout)
            # Configuration
        asya-runtime.md
            # Responsibilities (user code execution, processing input messages, generating output messages)
            # How it works (receives messages from sidecar, processes them, sends results back to sidecar)
            # How it is deployed (defined explicitly by user, but Asya injects entrypoint script asya_runtime.py that loads user code and handles communication with sidecar via Unix socket)
            # Supported Python 3.7+ (for old AI models)
            # Readiness probe (separate socket)
            # User code interface
            # - handlers - function/class
            # - payload/envelope modes and input/output message formats to user handler
            # - fan-out/abort semantics
            # - error propagation (user handler raises exception -> runtime sends error as dict back to sidecar)
            # - Route Modification Rules (append-only)
            # - how 'current' is incremented (in payload mode automatically, in envelope mode user must do it)
            # If unix socket connection lost (TODO)
            # Examples of runtimes (data processing, AI inference, etc)
            # asya_runtime.py via ConfigMap (src/asya-operator/RUNTIME_CONFIGMAP.md is very outdated - delete it and leave info here)
            # Configuration
        asya-operator.md
            # Responsibilities (manages lifecycle of actors, monitors health, scales actors based on load)
            # How it works (watches K8s resources, creates/updates/deletes actor pods, collects metrics)
            # How it is deployed (in central namespace asya-system)
            # Ownership of resources (Deployments, ScaledObjects, queues etc)
            # Queue creation and management
            # Integration with KEDA for autoscaling
            # Behavior on events:
                # AsyncActor CR is created
                # AsyncActor's Deployment is deleted
                # AsyncActor's Deployment is modified
                # AsyncActor's Queue is deleted
                # AsyncActor's Queue is modified (ignore)
                # Actor pod crashes
            # Observability features (metrics, logs)
            # Configuration
            # Deployment Helm charts
        asya-gateway.md
            # Responsibilities (exposes MCP-compliant HTTP API for sending/receiving messages to/from actors)
            # How it works (receives HTTP requests, creates envelopes, sends to actors via sidecars, receieves HTTP status updates from sidecars)
            # Stateful: stores envelope states in Postgresql database
            # Deployment as a separate Deployment in the same namespace as other actors
            # Configuration (TODO: check src/asya-gateway/config/README.md)
            # API endpoints (send message, receive status update)
            # Examples of tools
            # Deployment Helm charts
        asya-crew.md
            # Special actors for system-level tasks (e.g. logging, monitoring, message persistance, error handling)
            # Deployed in the same namespace as other actors
            # Current crew actors:
            # - error-end (now only s3 persistance, later also retry handling, report failure to gateway)
            # - happy-end (s3 persistance, report success to gateway)
            # Future crew actors:
            # - stateful fan-in crew actor
            # - TBD
        asya-cli.md
            # common CLI tools for interacting with Asya system
            # asya-mcp: tiny CLI for interacting with MCP Gateway (mostly testing)
            # asya-mcp-forward: port-forwarding tool for MCP Gateway testing
        observability.md  # TBD (no content for now)
            # Built-in OTEL metrics (actor processing time, message throughput, error rates)
            # Integration with Prometheus/Grafana
            # Metrics exposed by Sidecar, Runtime, Operator, Gateway
            # Example Grafana dashboards
        autoscaling.md
            # How it works (how KEDA's ScaledObjects work)
            # Benefits (automatic scaling, cost optimization, handling bursty workloads)
            # How Asya is integrated with KEDA (Asya creates KEDA ScaledObjects, which scales actor deployments based on message queue depth or custom metrics)
            # Configuration of autoscaling parameters
            # Examples of scaling scenarios
        protocols/
            actor-actor.md  # see inspiration in: docs_old/architecture/protocol-envelope.md
                # message vs envelope
                # Queue naming convention
                # ack/nack
                # end queues: happy-end, error-end (implicit by protocol, not in the route)
                # suggested: payload enrichment pattern (see /README.md, section "Mutating payloads")
            sidecar-runtime.md  # modified copy of docs_old/architecture/protocol-unix-socket.md
                # communication via unix socket
                # request/response pattern
                # timeouts
                # error handling
        transports/
            README.md  # are pluggable, etc etc
            sqs.md
            rabbitmq.md

    install/
        aws-eks.md  # should contain info from docs_old/guides/deploy-aws-requirements.md (verified) and deploy-aws-setup.md (might have outdated info)
            # Prerequisites (EKS cluster, kubectl, helm, awscli, eksctl)
            # VPC and Networking requirements
            # IAM roles and permissions
            # Optional components (EBS CSI Driver, Metrics Server, CloudWatch Container Insights)
            # Asya🎭 Deployment steps
        local-kind.md
            # Prerequisites (kind, kubectl, helm)
            # Create kind cluster with required config
            # Deploy Asya🎭 via Helm
        helm-charts.md
            # Overview of Helm charts for Asya components
            # asya-operator chart
            # asya-gateway chart
            # asya-actor chart
            # asya-crew chart

    operate/
        monitoring.md  # empty for now
        troubleshooting.md  # empty for now
        upgrades.md # empty for now
    quickstart/
        for-data_scientists.md  # setup local env, examples
            # how you see the framework as a data scientist
            # use asya-mcp tool to communicate with models via MCP Gateway
            # TODO (later) configure VScode or Claude to talk to mcp
        for-platform_engineers.md
            # how you see the framework as a platform engineer
