---
title: "ADR: Rejected — Placement Directory for Shard Affinity"
status: rejected
superseded_by: "rfc.md (actualized: no sharding needed with external state)"
date: 2025-02-23
---

# ADR: Placement Directory for Shard Affinity

## Status

**Rejected**. Preserved for historical context.

## Context

To make shard affinity work with dynamic scaling, a placement directory was
explored. This is the pattern used by Dapr (Placement Service), Vitess
(Lookup VIndex), and Akka (Shard Coordinator).

The placement directory maps `origin_id` (or a hash of it) to a specific
aggregator shard. When the shard count changes, the directory is updated
and in-flight keys are redistributed.

## Approaches Evaluated

### Static Hashing (Rendezvous / Consistent Hash)

Sender computes `hash(key) % N`. Scale events remap keys -- partial results
split across old and new shards.

### Stamped-N

Gateway stamps shard count into message at ingestion time. Problem: Gateway
must know N reliably; ConfigMap sync lag makes this unreliable. Stale N in
messages causes misrouting.

### Virtual Shards

`hash(key) % V` where V >> N (e.g., V=1024). Virtual shards mapped to
physical shards. Scale events reassign virtual shards. Problem: requires
state migration during reassignment.

### Semi-Stateful Router

Placement directory in embedded KV (Badger, SQLite). Router maintains a
mapping from key range to shard. Problem: Router is SPOF. HA requires
Raft consensus, adding ~300-500 LoC of custom consensus code.

## Placement Store Options

| Store | Consistency | Verdict |
|-------|-------------|---------|
| Embedded Badger (single-node) | CP (single writer) | SPOF |
| Embedded Badger + hashicorp/raft | CP (Raft) | ~300-500 LoC of custom consensus |
| NATS JetStream KV | CP (Raft) | Raft-limited throughput |
| Redis/Valkey | AP (async replication) | AP semantics break placement correctness |
| etcd | CP (Raft) | Overkill for routing table |

## Why Rejected

All placement directory approaches share fundamental problems:

1. **Scale events require coordinated state migration**: When the shard count
   changes, keys must be remapped. In-flight aggregations spanning the scale
   event have messages on both old and new shards.

2. **Adds distributed consensus complexity**: Any HA placement directory
   requires consensus (Raft, Paxos). This is a significant engineering
   investment for what should be a simple fan-in operation.

3. **SPOF or complexity tradeoff**: Single-node placement is SPOF. Multi-node
   placement requires consensus. Neither is simple.

4. **External state eliminates the need entirely**: With external state stores
   (S3, Redis), any pod can access any key. No placement directory needed.
   CAS or split-key patterns handle concurrency.

## Connection to Rejected Sharding Design

The placement directory was explored as part of the broader sharded-aggregator
design (see `adr.rejected.rendezvous-sharding-rocksdb.md`). Rendezvous hashing
was chosen over the placement directory because it's stateless (no directory to
maintain) and provides good redistribution properties (~1/N keys move on scale
change).

Both the placement directory AND rendezvous hashing were ultimately rejected
in favor of the no-sharding approach with external state.

## References

- Semi-Stateful Actors RFC (epic 1dmf) -- ADR-7 (Against shard affinity),
  ADR-8 (Against building a placement directory)
- Dapr Placement Service -- reference implementation of the pattern
- Akka Shard Coordinator -- reference implementation in the actor model space
