"""
Live streaming - stream LLM tokens to the UI in real-time.

Uses the ABI FLY verb to send tokens upstream to the gateway as they arrive
from the LLM. The gateway forwards them as SSE events to connected clients,
so the user sees text appearing token by token rather than waiting for the
full response.

FLY events bypass message queues — they travel directly via HTTP from the
sidecar to the gateway. The downstream envelope (with the full response) is
emitted after streaming completes.

FLY payload format (ADK-aligned):
  {"partial": True, "text": "<token>"}   -- streaming chunk

The final downstream `yield payload` acts as the non-partial (final) frame —
no explicit "done" FLY is needed. Mirrors ADK's Event(partial=True/False).

Deploy:
  ASYA_HANDLER=live_streaming.streaming_llm

See also:
  docs/tutorials/agentic-patterns.md (Pattern 2: Live streaming)
  docs/reference/abi-protocol.md (FLY verb)
"""

import os


async def streaming_llm(payload: dict):
    """LLM actor that streams tokens upstream while computing the response.

    Reads payload["query"], streams tokens to the gateway via FLY, then
    emits the complete response in payload["response"] downstream.

    Deploy as: ASYA_HANDLER=live_streaming.streaming_llm
    """
    query = payload.get("query", "")

    tokens = []
    async for token in _stream_tokens(query):
        # partial=True marks this as a streaming chunk — equivalent to ADK's
        # Event(partial=True, content=Part(text=token)). Not persisted to session,
        # not applied to state, forwarded to UI for real-time display.
        yield "FLY", {"partial": True, "text": token}
        tokens.append(token)

    # No explicit "done" FLY needed — the downstream yield payload below is the
    # final (non-partial) frame, equivalent to ADK's Event(partial=False, ...).
    payload["response"] = "".join(tokens)
    yield payload


async def _stream_tokens(query: str):
    """Token stream. Replace mock body with a real LLM API call.

    Mock implementation: splits a static sentence into words.

    Real implementation (Anthropic):

        import anthropic

        client = anthropic.AsyncAnthropic()
        async with client.messages.stream(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            messages=[{"role": "user", "content": query}],
        ) as stream:
            async for token in stream.text_stream:
                yield token

    Real implementation (OpenAI):

        import openai

        client = openai.AsyncOpenAI()
        stream = await client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": query}],
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
    """
    model = os.environ.get("ASYA_MOCK_MODEL", "mock")
    words = f"[{model}] Response to: {query}. Here is a streaming answer.".split()
    for word in words:
        yield word + " "
