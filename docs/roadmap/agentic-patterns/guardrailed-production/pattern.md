# Guardrailed Production AI (Safety Sandwich)

## Use-Case

Customer-facing AI that must pass input validation, output filtering, PII
detection, and compliance checks — with safe fallbacks on failure. Used in
regulated industries (healthcare, finance, legal) where AI output must meet
compliance standards before reaching users.

## Why Asya

- **Try/except in Flow DSL**: Compiles to resiliency policies in the sidecar.
  Safety isn't application code — it's infrastructure. Guardrails can't be
  accidentally bypassed by a developer forgetting a try/catch.
- **Each guardrail is a separate actor**: Input validator, PII detector, output
  filter — each maintained, versioned, and scaled independently. Security team
  owns guardrail actors; product team owns core agent.
- **DLQ routing**: If the core agent fails, sidecar routes to `x-sump`
  automatically. No unhandled failures reach users.
- **Audit trail**: Envelope carries full processing history including which
  guardrails passed/failed. Compliance team can inspect any request.
- **Independent deployment**: Update PII detector without redeploying core agent.
  Guardrail actors have their own release cycle.

## Architecture

```
Input
  |
  [try]
      |
      Input Validator (blocks prompt injection, jailbreaks)
      |
      PII Detector (redacts SSN, credit cards, etc.)
      |
      Core Agent (LLM reasoning)
      |
      Output Filter (blocks data leaks, harmful content)
      |
      Compliance Checker (regulatory rules)
  |
  [except]
      |
      Safe Fallback (polite refusal with audit log)
  |
  x-sink
```

## Example Flow

```python
@flow
async def safe_agent(p):
    try:
        p = await input_validator(p)
        p = await pii_detector(p)
        p = await core_agent(p)
        p = await output_filter(p)
        p = await compliance_checker(p)
    except:
        p = await safe_fallback(p)
    return p
```

## Key Properties

- **Guardrails are actors, not middleware**: Separate pods, separate secrets,
  separate scaling, separate deployment
- **Try/except is infrastructure**: Sidecar enforces routing on error, not
  application code
- **Audit trail for free**: Envelope payload contains validator results at
  each step
- **Fallback is guaranteed**: Even if core agent throws, safe_fallback runs
