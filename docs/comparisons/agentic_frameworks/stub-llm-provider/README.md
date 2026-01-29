# Stub LLM Provider

Local mock server for testing agentic frameworks without real API keys.

Uses [VidaiMock](https://github.com/vidaiUK/VidaiMock) - a high-fidelity LLM simulation server that supports OpenAI, Anthropic, and Gemini wire protocols.

## Quick Start

```bash
# Start the stub server
docker compose up -d

# Verify it's running
curl http://localhost:8100/health
```

## Endpoints

| Provider | Endpoint | Base URL |
|----------|----------|----------|
| OpenAI | `/v1/chat/completions` | `http://localhost:8100` |
| Anthropic | `/v1/messages` | `http://localhost:8100` |
| Gemini | `/v1beta/models/*` | `http://localhost:8100` |

## Framework Compatibility

| Framework | Works | Notes |
|-----------|-------|-------|
| Anthropic SDK | ✅ | Uses `/v1/messages` |
| LangGraph | ✅ | Uses Anthropic via langchain-anthropic |
| CrewAI | ✅ | Uses `/v1/chat/completions` |
| Google ADK | ✅ | Uses `/v1beta/models/*` via StubGemini class |
| DSPy | ⚠️ | Has built-in mock mode; litellm routing issues |
| OpenAI Agents | ❌ | Uses `/v1/responses` (not supported yet) |

## Framework Configuration

Source the environment file to configure all frameworks:

```bash
source stub-llm-provider/.env.stub
```

### Google ADK
Uses `STUB_AI_BASE_URL` environment variable with custom `StubGemini` class in main.py.

### LangGraph / Anthropic SDK
Uses `ANTHROPIC_BASE_URL` environment variable.

### CrewAI
Uses `OPENAI_BASE_URL` environment variable.

### DSPy
Has built-in mock mode when `OPENAI_API_KEY` is not set. Litellm routing may not work with stub.

### OpenAI Agents
Not supported - uses `/v1/responses` endpoint which VidaiMock doesn't implement yet.

## Custom Responses

Place custom response templates in `config/` directory. VidaiMock uses Tera templates for dynamic responses.

Example custom response (`config/custom.yaml`):
```yaml
routes:
  - path: /v1/chat/completions
    response:
      model: "gpt-4o-mini"
      choices:
        - message:
            role: "assistant"
            content: "This is a test response from the stub server."
```

## Features

- Physics-accurate streaming (TTFT, token-by-token delivery)
- Native SSE/EventStream formats per provider
- Chaos testing (inject failures, latency)
- ~50,000 RPS performance

## Sources

- [VidaiMock GitHub](https://github.com/vidaiUK/VidaiMock)
- [Vidai Platform](https://vidai.uk/platform/mock)
