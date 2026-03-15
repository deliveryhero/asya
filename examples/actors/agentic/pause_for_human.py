"""
Pause for human input - suspend pipeline at a checkpoint for human review.

Asya equivalent of ADK's long-running tool / pause-resume pattern. When the
actor determines that human input is required, it prepends x-pause to
route.next via the ABI SET verb. The x-pause crew actor then handles
persistence, signals the gateway via x-asya-pause, and the gateway marks
the task as paused (A2A: input_required).

Resume flow:
  1. Actor routes to x-pause (this file)
  2. x-pause crew persists the envelope, signals gateway
  3. Gateway marks task as input_required, notifies client
  4. Client sends human input via A2A task endpoint (same task ID)
  5. Gateway routes to x-resume with x-asya-resume-task header
  6. x-resume merges human input into payload, re-enqueues to next actor
  7. post_approval actor (this file) continues with human input in payload

Route configuration (example):
  analyst -> x-pause -> x-resume -> post_approval -> x-sink

Or dynamically at runtime (this file's approach):
  analyst prepends x-pause to route.next when risk_level == "high"

Deploy:
  ASYA_HANDLER=pause_for_human.analyst         (first actor)
  ASYA_HANDLER=pause_for_human.post_approval   (runs after resume)

See also:
  docs/tutorials/agentic-patterns.md (Pattern 3: Pause for human input)
  examples/flows/agentic/human_in_the_loop.py (Flow DSL: poll-based approval loop)
"""


async def analyst(payload: dict):
    """Analysis actor that pauses for human review on high-risk decisions.

    If the analysis result is high-risk, prepends x-pause to route.next.
    x-pause crew actor handles gateway signaling and message persistence.
    The _pause_metadata field tells the human-facing UI what to ask.

    Deploy as: ASYA_HANDLER=pause_for_human.analyst
    """
    result = await _analyze(payload)
    payload["analysis"] = result

    if result.get("risk_level") == "high":
        # Signal pause: x-pause crew actor handles the rest
        yield "SET", ".route.next[:0]", ["x-pause"]

        # Pause metadata is read by x-pause and stored for the human-facing UI.
        # The fields list defines what the human needs to fill in.
        payload["_pause_metadata"] = {
            "prompt": (
                f"High-risk action detected: {result['action']}. "
                "Review the analysis and approve or reject before proceeding."
            ),
            "fields": [
                {
                    "name": "approved",
                    "type": "boolean",
                    "label": "Approve action",
                    "required": True,
                },
                {
                    "name": "notes",
                    "type": "string",
                    "label": "Notes (shown in audit log)",
                    "required": False,
                },
            ],
        }

    yield payload


async def post_approval(payload: dict):
    """Continues after human provides input via A2A resume.

    The x-resume crew actor merges human input into the payload before
    routing here. Reads payload["approved"] and payload["notes"].

    Deploy as: ASYA_HANDLER=pause_for_human.post_approval
    """
    if not payload.get("approved"):
        payload["status"] = "rejected"
        payload["rejection_reason"] = payload.get("notes", "No reason provided")
        yield payload
        return

    result = await _execute(payload)
    payload["execution_result"] = result
    payload["status"] = "completed"
    if payload.get("notes"):
        payload["audit_notes"] = payload["notes"]

    yield payload


# --- Mock implementations ---


async def _analyze(payload: dict) -> dict:
    """Mock risk analysis. Replace with real LLM or rule-based analysis.

    Real implementation: call an LLM with the payload context to assess risk,
    or apply a rules engine to classify the action.
    """
    action = payload.get("action", "unknown action")
    high_risk_keywords = ("delete", "drop", "destroy", "production", "irreversible")
    risk_level = "high" if any(kw in action.lower() for kw in high_risk_keywords) else "low"
    return {
        "action": action,
        "risk_level": risk_level,
        "recommendation": "manual review required" if risk_level == "high" else "proceed",
    }


async def _execute(payload: dict) -> dict:
    """Execute the approved action. Replace with real implementation."""
    return {
        "status": "completed",
        "action": payload.get("analysis", {}).get("action", "unknown"),
    }
