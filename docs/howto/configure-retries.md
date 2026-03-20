<!-- Type: How-to -->

# How to Configure Retries

Practical recipes for configuring retry behavior on Asya actors using
resiliency policies and error-matching rules.

For the full policy schema, rule matching semantics, and envelope status
fields, see [Resiliency Reference](../features/resiliency.md).

---

## Retry with exponential backoff

```bash
ASYA_RESILIENCY_POLICIES='{"default":{"maxAttempts":5,"backoff":"exponential","initialDelay":"2s","maxInterval":"60s","jitter":true}}'
```

## Non-retryable errors go directly to x-sink

Configure a policy with `maxAttempts=1` and a rule that routes specific error
types to it. On the first failure, the policy is exhausted immediately.

```bash
ASYA_RESILIENCY_POLICIES='{
  "default":    {"maxAttempts":3,"backoff":"exponential","initialDelay":"1s"},
  "hard-fail":  {"maxAttempts":1}
}'
ASYA_RESILIENCY_RULES='[
  {"errors":["ValueError","TypeError"],"policy":"hard-fail"}
]'
```

## Route exhausted envelopes to a recovery actor

When the policy exhausts, instead of going to `x-sink`, the envelope is forwarded
to a recovery actor that can inspect or reprocess it:

```bash
ASYA_RESILIENCY_POLICIES='{"default":{"maxAttempts":3,"backoff":"constant","initialDelay":"5s","onExhausted":["recovery-actor"]}}'
```

The recovery actor receives the envelope with `status.phase=failed` and
`status.reason=PolicyRouted`.

## Cap total retry time

Stop retrying after 10 minutes regardless of attempt count:

```bash
ASYA_RESILIENCY_POLICIES='{"default":{"maxAttempts":100,"backoff":"exponential","initialDelay":"1s","maxInterval":"30s","maxDuration":"10m"}}'
```

---

## See also

- [Resiliency Reference](../features/resiliency.md) — policy schema, rule
  matching, backoff strategies, envelope status fields, transport constraints
