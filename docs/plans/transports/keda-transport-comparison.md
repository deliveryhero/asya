# KEDA Transport Comparison for Asya🎭

## Overview

This document compares message queue and event streaming transports that could be integrated into Asya🎭 based on their KEDA scaler support. The comparison focuses on feasibility for async actor workloads with event-driven autoscaling.

## Status Legend

- ✅ **Supported** - Currently implemented in Asya🎭
- 🟢 **High Priority** - Strong fit for Asya🎭 use cases
- 🟡 **Medium Priority** - Viable but with trade-offs
- 🔴 **Low Priority** - Limited applicability or significant challenges

## Quick Comparison Matrix

| Transport | Status | Latency | Throughput | Durability | Ack/Nack | Ordering | K8s Maturity | KEDA Support | Ops Complexity | Routing Flexibility | License |
|-----------|--------|---------|------------|------------|----------|----------|--------------|--------------|----------------|---------------------|---------|
| **RabbitMQ** | ✅ | Low (5-20ms) | Medium-High (50K msg/s) | High (persistent) | ✅ Yes | ✅ Queue-level | ✅ Excellent | ✅ Native | Medium | ✅ Excellent (exchanges, routing keys) | MPL 2.0 |
| **AWS SQS** | ✅ | Medium (10-100ms) | High (unlimited) | High (replicated) | ✅ Yes | ⚠️ FIFO only | ✅ Excellent | ✅ Native | Low (managed) | ⚠️ Basic (no routing) | Proprietary |
| **Apache Kafka** | 🟢 | Low (2-10ms) | Very High (1M+ msg/s) | Very High (replicated log) | ⚠️ Offset-based | ✅ Partition-level | ✅ Excellent | ✅ Native | High | ⚠️ Topic-based | Apache 2.0 |
| **Redis Streams** | 🟢 | Very Low (1-5ms) | High (100K+ msg/s) | Medium (AOF/RDB) | ⚠️ Consumer groups | ✅ Stream-level | ✅ Excellent | ✅ Native | Low-Medium | ⚠️ Basic (key patterns) | BSD 3-Clause |
| **NATS JetStream** | 🟢 | Very Low (1-3ms) | Very High (10M+ msg/s) | High (replicated) | ✅ Yes | ✅ Stream-level | 🟢 Good | ✅ Native | Low | 🟢 Good (subjects, wildcards) | Apache 2.0 |
| **Azure Service Bus** | 🟡 | Medium (10-50ms) | Medium-High (100K msg/s) | High (replicated) | ✅ Yes | ✅ Session-based | ✅ Excellent | ✅ Native | Low (managed) | 🟢 Good (topics, filters) | Proprietary |
| **GCP Pub/Sub** | 🟡 | Medium (50-200ms) | Very High (unlimited) | High (replicated) | ✅ Yes | ⚠️ Best-effort | ✅ Excellent | ✅ Native | Low (managed) | ⚠️ Basic (attributes) | Proprietary |
| **Apache Pulsar** | 🟡 | Low (5-15ms) | Very High (1M+ msg/s) | Very High (BookKeeper) | ✅ Yes | ✅ Partition-level | 🟢 Good | ✅ Native | Very High | ✅ Excellent (multi-tenant) | Apache 2.0 |
| **Azure Event Hubs** | 🟡 | Low (5-20ms) | Very High (1M+ msg/s) | High (replicated) | ⚠️ Checkpoint-based | ✅ Partition-level | ✅ Excellent | ✅ Native | Low (managed) | ⚠️ Partition-based | Proprietary |
| **AWS Kinesis** | 🟡 | Medium (70-200ms) | High (1M records/s) | High (replicated) | ⚠️ Checkpoint-based | ✅ Shard-level | ✅ Excellent | ✅ Native | Low (managed) | ⚠️ Shard-based | Proprietary |
| **ActiveMQ** | 🔴 | Medium (10-50ms) | Medium (20K msg/s) | High (persistent) | ✅ Yes | ✅ Queue-level | 🟢 Good | ✅ Native | Medium-High | 🟢 Good (topics, selectors) | Apache 2.0 |
| **IBM MQ** | 🔴 | Low (5-15ms) | Medium (50K msg/s) | Very High (transactional) | ✅ Yes | ✅ Queue-level | 🟡 Limited | 🟡 Via Prometheus | Very High | 🟢 Good (topics, routing) | Proprietary |
| **RabbitMQ Streams** | 🟢 | Very Low (2-8ms) | Very High (1M+ msg/s) | Very High (append-only log) | ⚠️ Offset-based | ✅ Stream-level | ✅ Excellent | ✅ Native | Medium | 🟢 Good (stream topology) | MPL 2.0 |

## Detailed Analysis

### Currently Supported

#### RabbitMQ ✅
**KEDA Scaler**: `rabbitmq`

**Strengths**:
- Mature message broker with excellent K8s ecosystem (operator, Helm charts)
- Rich routing capabilities (exchanges, bindings, routing keys, dead-letter queues)
- Strong durability with message persistence and clustering
- Native KEDA support with queue-length and stream-lag metrics
- Well-suited for async actor patterns with complex workflows

**Weaknesses**:
- Cluster management complexity increases at scale
- Lower throughput vs. streaming platforms (Kafka, Pulsar)
- Memory-based storage can be limiting for high-volume scenarios

**Asya🎭 Fit**: ⭐⭐⭐⭐⭐ (Excellent baseline choice)

**Implementation Notes**:
- Current implementation in `operator/internal/controller/keda.go:162`
- Uses `QueueLength` mode for autoscaling
- Supports authentication via TriggerAuthentication

---

#### AWS SQS ✅
**KEDA Scaler**: `aws-sqs-queue`

**Strengths**:
- Fully managed (zero operational overhead)
- Unlimited scalability
- Strong durability (cross-AZ replication)
- Native AWS integration (IAM roles, VPC endpoints)
- Cost-effective for variable workloads

**Weaknesses**:
- Higher latency vs. self-hosted solutions
- No native routing (requires separate queues per route)
- FIFO queues have throughput limits (3K msg/s per queue)
- Vendor lock-in

**Asya🎭 Fit**: ⭐⭐⭐⭐ (Excellent for AWS deployments)

**Implementation Notes**:
- Current implementation in `operator/internal/controller/keda.go:132`
- Uses pod identity for authentication
- Queue URL constructed from base URL + queue name

---

### High Priority Candidates

#### Apache Kafka 🟢
**KEDA Scaler**: `kafka`

**Strengths**:
- Industry-standard event streaming platform
- Extremely high throughput (millions of messages/second)
- Excellent durability (distributed commit log with replication)
- Strong ecosystem (Strimzi operator, Confluent Cloud)
- Partition-level ordering guarantees
- Message replay capability

**Weaknesses**:
- Higher operational complexity (ZooKeeper/KRaft, partition management)
- Consumer offset management vs. traditional ack/nack
- Overkill for simple queue-based workflows
- Higher resource requirements

**Asya🎭 Fit**: ⭐⭐⭐⭐ (Excellent for high-throughput streaming)

**Use Cases**:
- Event sourcing patterns
- High-volume data pipelines (e.g., LLM inference batching)
- Scenarios requiring message replay
- Multi-consumer fan-out patterns

**KEDA Integration**:
```yaml
triggers:
  - type: kafka
    metadata:
      bootstrapServers: kafka.kafka.svc:9092
      consumerGroup: actor-group
      topic: actor-input
      lagThreshold: '5'
```

---

#### Redis Streams 🟢
**KEDA Scaler**: `redis-streams`

**Strengths**:
- Very low latency (sub-millisecond)
- Simple operational model
- Excellent K8s support (Redis Operator, Redis Enterprise)
- Consumer groups for competing consumers
- Memory-efficient for moderate volumes
- Often already deployed for caching

**Weaknesses**:
- Durability depends on persistence configuration (AOF/RDB trade-offs)
- Memory-bound (not ideal for very large backlogs)
- Limited routing flexibility vs. RabbitMQ
- Single-threaded core (scaling via clustering)

**Asya🎭 Fit**: ⭐⭐⭐⭐ (Excellent for low-latency scenarios)

**Use Cases**:
- Real-time processing (e.g., streaming inference)
- Scenarios where Redis is already deployed
- Low-latency requirements (<10ms)
- Moderate message volumes

**KEDA Integration**:
```yaml
triggers:
  - type: redis-streams
    metadata:
      address: redis.redis.svc:6379
      stream: actor-stream
      consumerGroup: actor-cg
      pendingEntriesCount: '5'
```

---

#### NATS JetStream 🟢
**KEDA Scaler**: `nats-jetstream`

**Strengths**:
- Extremely low latency (microsecond range)
- Very high throughput (10M+ msgs/sec)
- Cloud-native design (CNCF project)
- Simple deployment model
- Built-in clustering and HA
- Subject-based routing with wildcards
- Excellent K8s integration

**Weaknesses**:
- Smaller ecosystem vs. Kafka/RabbitMQ
- Less mature operator tooling
- Fewer third-party integrations

**Asya🎭 Fit**: ⭐⭐⭐⭐⭐ (Excellent cloud-native choice)

**Use Cases**:
- Microservices communication
- Edge computing scenarios
- High-throughput + low-latency requirements
- Cloud-native architectures

**KEDA Integration**:
```yaml
triggers:
  - type: nats-jetstream
    metadata:
      natsServerMonitoringEndpoint: nats.nats.svc:8222
      stream: actor-stream
      consumer: actor-consumer
      lagThreshold: '5'
```

---

#### RabbitMQ Streams 🟢
**KEDA Scaler**: `rabbitmq` (stream mode)

**Strengths**:
- Combines RabbitMQ's ecosystem with Kafka-like streaming
- Append-only log with offset tracking
- Very high throughput (1M+ msgs/sec per stream)
- Lower latency than classic queues
- Leverages existing RabbitMQ infrastructure
- Message replay capability

**Weaknesses**:
- Requires RabbitMQ 3.9+ with streams plugin
- Different programming model vs. classic queues
- Less mature than Kafka for streaming

**Asya🎭 Fit**: ⭐⭐⭐⭐⭐ (Excellent evolution path)

**Use Cases**:
- Teams already using RabbitMQ wanting streaming capabilities
- Hybrid queue + stream architectures
- High-throughput scenarios with RabbitMQ expertise

**KEDA Integration**:
```yaml
triggers:
  - type: rabbitmq
    metadata:
      queueName: actor-stream
      mode: StreamLag  # vs QueueLength
      value: '5'
```

---

### Medium Priority Candidates

#### Azure Service Bus 🟡
**KEDA Scaler**: `azure-servicebus`

**Strengths**:
- Fully managed Azure offering
- Enterprise messaging features (sessions, transactions)
- Good routing (topics, subscriptions, filters)
- Strong durability

**Weaknesses**:
- Azure-specific (vendor lock-in)
- Higher cost vs. open-source options
- Medium latency

**Asya🎭 Fit**: ⭐⭐⭐ (Good for Azure-centric deployments)

---

#### GCP Pub/Sub 🟡
**KEDA Scaler**: `gcp-pubsub`

**Strengths**:
- Fully managed GCP offering
- Unlimited scalability
- Global distribution
- Strong durability

**Weaknesses**:
- Highest latency of managed options
- GCP-specific (vendor lock-in)
- Basic routing (attribute-based filtering)
- Best-effort ordering only

**Asya🎭 Fit**: ⭐⭐⭐ (Good for GCP-centric deployments)

---

#### Apache Pulsar 🟡
**KEDA Scaler**: `pulsar`

**Strengths**:
- Multi-tenancy built-in
- Unified messaging + streaming
- Geo-replication
- Very high throughput and durability (BookKeeper)

**Weaknesses**:
- Very high operational complexity
- Heavy resource requirements
- Smaller community vs. Kafka
- Steep learning curve

**Asya🎭 Fit**: ⭐⭐⭐ (Good for large-scale multi-tenant scenarios)

---

#### Azure Event Hubs 🟡
**KEDA Scaler**: `azure-eventhub`

**Strengths**:
- Kafka-compatible API
- Fully managed
- Very high throughput

**Weaknesses**:
- Azure-specific
- Checkpoint-based ack model
- Higher cost

**Asya🎭 Fit**: ⭐⭐⭐ (Good for Azure event streaming)

---

#### AWS Kinesis 🟡
**KEDA Scaler**: `aws-kinesis-stream`

**Strengths**:
- Fully managed streaming
- AWS integration
- Good durability

**Weaknesses**:
- Higher latency vs. Kafka
- Shard management complexity
- Checkpoint-based ack
- AWS-specific

**Asya🎭 Fit**: ⭐⭐⭐ (Good for AWS streaming scenarios)

---

### Low Priority Candidates

#### ActiveMQ 🔴
**KEDA Scaler**: `activemq`

**Strengths**:
- Mature JMS implementation
- Good routing capabilities

**Weaknesses**:
- Lower throughput
- Declining community support (superseded by Artemis)
- Medium-high operational complexity

**Asya🎭 Fit**: ⭐⭐ (Legacy scenarios only)

---

#### IBM MQ 🔴
**KEDA Scaler**: Limited (Prometheus-based custom metrics)

**Strengths**:
- Enterprise-grade reliability
- Strong transactional guarantees

**Weaknesses**:
- Very high operational complexity
- Proprietary licensing
- Limited K8s ecosystem
- Weak KEDA integration

**Asya🎭 Fit**: ⭐ (Enterprise lock-in scenarios only)

---

## Recommendations

### Immediate Next Steps (2024 Q4 - 2025 Q1)

1. **NATS JetStream** 🟢
   - **Priority**: High
   - **Rationale**: Cloud-native, low latency, simple ops, excellent K8s fit
   - **Effort**: Medium (new transport abstraction)
   - **Impact**: Opens edge computing and real-time use cases

2. **Redis Streams** 🟢
   - **Priority**: High
   - **Rationale**: Low latency, often already deployed, simple
   - **Effort**: Low (similar to RabbitMQ implementation)
   - **Impact**: Enables sub-10ms processing pipelines

3. **RabbitMQ Streams** 🟢
   - **Priority**: Medium
   - **Rationale**: Leverage existing RabbitMQ knowledge, high throughput
   - **Effort**: Low (extends existing RabbitMQ support)
   - **Impact**: 10x throughput improvement for existing RabbitMQ users

### Future Expansion (2025 Q2+)

4. **Apache Kafka** 🟢
   - **Priority**: High (but deferred)
   - **Rationale**: Industry standard for event streaming
   - **Effort**: High (different ack model, partition management)
   - **Impact**: Critical for enterprise adoption

5. **Azure Service Bus** 🟡
   - **Priority**: Medium
   - **Rationale**: Azure cloud customers
   - **Effort**: Medium
   - **Impact**: Reduces Azure friction

6. **GCP Pub/Sub** 🟡
   - **Priority**: Medium
   - **Rationale**: GCP cloud customers
   - **Effort**: Medium
   - **Impact**: Reduces GCP friction

### Implementation Strategy

#### Phase 1: Transport Abstraction
- Refactor sidecar to use pluggable transport interface
- Extract RabbitMQ implementation behind interface
- Define standard transport SPI (Service Provider Interface)

#### Phase 2: High-Priority Transports
- Implement NATS JetStream transport
- Implement Redis Streams transport
- Implement RabbitMQ Streams mode
- Document transport selection guide

#### Phase 3: Enterprise Expansion
- Implement Kafka transport (with offset management)
- Implement Azure Service Bus transport
- Implement GCP Pub/Sub transport

#### Phase 4: Edge Cases
- Evaluate ActiveMQ Artemis (vs. classic ActiveMQ)
- Evaluate Pulsar for multi-tenant scenarios
- Support hybrid transport scenarios (multi-transport actors)

## Transport Selection Guide (Future)

**Choose RabbitMQ** when:
- Complex routing requirements (exchanges, bindings)
- Moderate throughput (<100K msgs/sec)
- Need mature ecosystem and tooling
- Team has RabbitMQ expertise

**Choose NATS JetStream** when:
- Very low latency required (<5ms)
- Cloud-native architecture
- Simple operational requirements
- High throughput + low resource footprint

**Choose Redis Streams** when:
- Redis already deployed
- Very low latency (<10ms)
- Moderate message volumes
- Simple use cases

**Choose Kafka** when:
- Very high throughput (>100K msgs/sec)
- Event sourcing patterns
- Message replay required
- Strong ordering guarantees critical

**Choose AWS SQS** when:
- AWS deployment
- Zero operational overhead desired
- Variable workloads
- Cost optimization priority

**Choose RabbitMQ Streams** when:
- Using RabbitMQ but need streaming
- High throughput + offset tracking
- Message replay required
- Leverage existing RabbitMQ skills

## KEDA Scaler References

All transports listed have native KEDA scalers. See official KEDA documentation:

- RabbitMQ: https://keda.sh/docs/latest/scalers/rabbitmq-queue/
- AWS SQS: https://keda.sh/docs/latest/scalers/aws-sqs/
- Kafka: https://keda.sh/docs/latest/scalers/apache-kafka/
- Redis Streams: https://keda.sh/docs/latest/scalers/redis-streams/
- NATS JetStream: https://keda.sh/docs/latest/scalers/nats-jetstream/
- Azure Service Bus: https://keda.sh/docs/latest/scalers/azure-service-bus/
- GCP Pub/Sub: https://keda.sh/docs/latest/scalers/gcp-pub-sub/
- Pulsar: https://keda.sh/docs/latest/scalers/apache-pulsar/
- Azure Event Hubs: https://keda.sh/docs/latest/scalers/azure-event-hub/
- AWS Kinesis: https://keda.sh/docs/latest/scalers/aws-kinesis/
- ActiveMQ: https://keda.sh/docs/latest/scalers/activemq/

## Migration Considerations

### Transport Interface Design

```go
// Transport interface for message consumption
type Transport interface {
    // Consume starts consuming messages from the queue
    Consume(ctx context.Context, queueName string) (<-chan Envelope, error)

    // Publish sends a message to the next queue in the route
    Publish(ctx context.Context, queueName string, envelope Envelope) error

    // Ack acknowledges successful processing
    Ack(ctx context.Context, deliveryID string) error

    // Nack negatively acknowledges (retry or DLQ)
    Nack(ctx context.Context, deliveryID string) error

    // HealthCheck verifies transport connectivity
    HealthCheck(ctx context.Context) error
}
```

### Operator CRD Updates

```yaml
# Example: Multi-transport support
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: my-actor
spec:
  transport: nats-jetstream  # Transport name from operator config
  queueName: my-queue
  scaling:
    enabled: true
    queueLength: 5
  # Transport-specific overrides
  transportConfig:
    nats:
      maxDeliver: 3
      ackWait: 30s
```

## License Considerations

**Open Source** (preferred for Asya🎭 base):
- RabbitMQ (MPL 2.0)
- Kafka (Apache 2.0)
- NATS (Apache 2.0)
- Redis (BSD 3-Clause)
- Pulsar (Apache 2.0)
- ActiveMQ (Apache 2.0)

**Proprietary** (managed service):
- AWS SQS
- AWS Kinesis
- Azure Service Bus
- Azure Event Hubs
- GCP Pub/Sub
- IBM MQ

---

**Document Status**: Draft for discussion
**Last Updated**: 2025-01-XX
**Author**: AI Analysis
**Next Steps**: Review with team, prioritize based on user demand
