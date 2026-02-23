## RFC: Typed Handler Signatures

> Extracted from epic [[1c84.handler-signature-redesign]]. See also: [[1ixt]] (message metadata vfs), [[1irj]] (flow free vars & iteration).

---

### 1. Overview

#### Problem

Today every Asya handler receives the entire payload as an untyped `dict` and returns an untyped `dict`:

```python
def analyze(payload: dict) -> dict:
    text = payload["text"]
    lang = payload["language"]
    return {"sentiment": score, "confidence": conf}
```

This has three consequences:

1. **No compile-time safety.** Typos in key names (`payload["langauge"]`) surface only at runtime.
2. **No schema generation.** The gateway cannot expose an actor's expected inputs/outputs as an MCP tool definition without a hand-written YAML schema.
3. **Tight coupling to payload shape.** Moving an actor from one pipeline to another requires rewriting key access whenever the surrounding payload structure changes.

#### Goal

Allow handlers to declare typed input and output parameters that the runtime extracts from (and merges back into) the payload. Mapping between payload paths and handler arguments is controlled by deployment-time environment variables, so the same handler code works across different pipelines without modification.

```python
from pydantic import BaseModel

class WeatherRequest(BaseModel):
    city: str
    units: str = "metric"

class WeatherResult(BaseModel):
    temperature: float
    description: str

async def get_weather(request: WeatherRequest) -> WeatherResult:
    data = await weather_api.fetch(request.city, request.units)
    return WeatherResult(temperature=data.temp, description=data.desc)
```

Deployed with `ASYA_HANDLER_INPUT=/` and `ASYA_HANDLER_OUTPUT=/weather`, the runtime receives payload:
```json
{"request": {"city": "New York", "units": "metric"}}
```
extracts `request` from payload root (by parameter name), calls the handler, and merges the result into `payload["weather"]`:
```json
{"request": {"city": "New York", "units": "metric"}, "weather": {"temperature": 70, "description": "good weather"}}
```


Or even primitive types (same request/response when deployed with `ASYA_HANDLER_INPUT=/request` and `ASYA_HANDLER_OUTPUT=/weather`):

```python
async def get_weather(city: str, units: str = "metric") -> float:
    data = await weather_api.fetch(city, units)
    return data.temp
```


#### Non-goals

- Replacing `/tmp/msg/` metadata access (that is epic 1ixt).
- Adding an `asya` pip package or framework-specific imports.
- Loop constructs in flow DSL (that is epic 1irj).
- Changing the sidecar-runtime wire protocol.

---

### 2. Input mapping (`ASYA_HANDLER_INPUT`)

#### Env var

| Variable | Default | Description |
|---|---|---|
| `ASYA_HANDLER_INPUT` | `/` | JSONPath-like subpath from which handler arguments are extracted |

The path uses `/`-separated segments to navigate into the payload dict. `/` means the payload root.

#### Extraction rules

The runtime inspects the handler signature with `inspect.signature()`. For each parameter (excluding `self` for class methods), it looks up a key matching the parameter name within the subtree selected by `ASYA_HANDLER_INPUT`.

**Example: root extraction (`ASYA_HANDLER_INPUT=/`)**

```python
def handler(weather: str, image: ImageModel):
    ...
```

Payload:
```json
{
  "weather": "sunny",
  "image": {"url": "https://...", "width": 640},
  "other_field": "untouched"
}
```

Runtime extracts `payload["weather"]` and `payload["image"]`, deserializes them into the declared types, and calls `handler(weather="sunny", image=ImageModel(...))`.

**Example: nested extraction (`ASYA_HANDLER_INPUT=/context`)**

```python
def handler(weather: str, image: ImageModel):
    ...
```

Payload:
```json
{
  "context": {
    "weather": "sunny",
    "image": {"url": "https://...", "width": 640}
  },
  "request_id": "abc"
}
```

Runtime extracts `payload["context"]["weather"]` and `payload["context"]["image"]`.

#### Missing keys

If a required parameter (no default value) is missing from the input subtree, the runtime returns a `processing_error` to the sidecar with a descriptive message listing the missing parameter name and the input path.

Optional parameters (those with defaults in the signature) are omitted from extraction when the key is absent, and the handler receives the default value.

#### Single-parameter `dict` fallback

If the handler has exactly one parameter annotated as `dict` (or untyped), the runtime passes the entire input subtree as-is with no extraction. This preserves backward compatibility with existing `payload: dict` handlers.

```python
# Legacy form -- no extraction, full subtree passed as dict
def handler(payload: dict) -> dict:
    return {"result": payload["text"].upper()}
```

---

### 3. Output mapping (`ASYA_HANDLER_OUTPUT`)

#### Env var

| Variable | Default | Description |
|---|---|---|
| `ASYA_HANDLER_OUTPUT` | `/` | JSONPath-like subpath where handler result is merged into payload |

#### Merge target

The handler's return value (serialized to `dict` if it is a model) is merged into the payload at the path specified by `ASYA_HANDLER_OUTPUT`.

**Example: root output (`ASYA_HANDLER_OUTPUT=/`)**

```python
def handler(text: str) -> dict:
    return {"sentiment": "positive", "score": 0.95}
```

Before: `{"text": "great", "lang": "en"}`
After: `{"text": "great", "lang": "en", "sentiment": "positive", "score": 0.95}`

**Example: nested output (`ASYA_HANDLER_OUTPUT=/analyzed`)**

Same handler, same return value.

Before: `{"text": "great", "lang": "en"}`
After: `{"text": "great", "lang": "en", "analyzed": {"sentiment": "positive", "score": 0.95}}`

**Example: deep nested output (`ASYA_HANDLER_OUTPUT=/results/nlp`)**

Before: `{"text": "great", "results": {"vision": {...}}}`
After: `{"text": "great", "results": {"vision": {...}, "nlp": {"sentiment": "positive", "score": 0.95}}}`

Intermediate dicts are created automatically if they do not exist.

#### `None` return

If the handler returns `None`, the payload is left unchanged and the message is routed to `x-sink` (abort semantics, same as today).

#### `dict` return from legacy handlers

If the single-parameter `dict` fallback is active (section 2), the return value replaces the entire input subtree rather than merging. This matches current payload-mode behavior exactly.

---

### 4. Merge semantics

When the handler returns a typed result (not the `dict` fallback), the runtime performs a **shallow merge** at the output path:

1. The return value is serialized to a flat `dict` (via `.model_dump()`, `dataclasses.asdict()`, or `dict()` depending on type).
2. Each top-level key in the result dict is written into the target subtree.
3. Keys present in the target but absent from the result are **preserved** (not deleted).
4. Keys present in both are **overwritten** by the result.

**Example:**

Output path: `/analyzed`

Target before handler:
```json
{"analyzed": {"foo": "bar", "baz": "zoo", "keep": true}}
```

Handler returns:
```json
{"foo": "kek", "new_field": 42}
```

Target after merge:
```json
{"analyzed": {"foo": "kek", "baz": "zoo", "keep": true, "new_field": 42}}
```

This is a standard `dict.update()` at the output path -- predictable and debuggable.

#### Scalar returns

If the handler's return type annotation is a scalar (e.g., `-> str`, `-> int`, `-> float`, `-> bool`), the runtime writes the value directly at the output path rather than merging:

```python
def classify(text: str) -> str:
    return "positive"
```

With `ASYA_HANDLER_OUTPUT=/sentiment`:

Before: `{"text": "great"}`
After: `{"text": "great", "sentiment": "positive"}`

#### List returns

Similarly, `-> list` or `-> List[...]` writes the list directly at the output path, no merge.

---

### 5. Type introspection and deserialization

The runtime uses `inspect.signature()` and `typing.get_type_hints()` (when available) to determine parameter types. Deserialization is performed per-parameter based on the annotation.

#### Supported type forms

| Annotation | Detection | Deserialization |
|---|---|---|
| `str`, `int`, `float`, `bool` | Built-in type | Direct pass-through (JSON already provides the correct type) |
| `list`, `List[T]` | Built-in / `typing` | Direct pass-through; no element-level validation |
| `dict`, `Dict[K, V]` | Built-in / `typing` | Direct pass-through |
| Pydantic `BaseModel` | `hasattr(cls, 'model_validate')` | `cls.model_validate(value)` (Pydantic v2) or `cls.parse_obj(value)` (v1) |
| `TypedDict` | `hasattr(cls, '__annotations__')` and `is_typeddict()` | Direct pass-through (TypedDict is a dict at runtime) |
| `dataclass` | `dataclasses.is_dataclass(cls)` | `cls(**value)` |
| No annotation | N/A | Direct pass-through (raw JSON value) |

#### Return value serialization

| Return type | Serialization |
|---|---|
| `dict` | Used as-is |
| Pydantic `BaseModel` | `.model_dump()` (v2) or `.dict()` (v1) |
| `dataclass` | `dataclasses.asdict()` |
| `TypedDict` | Used as-is (already a dict) |
| Scalar (`str`, `int`, etc.) | Written directly at output path |
| `list` | Written directly at output path |
| `None` | Abort (route to x-sink) |

#### No `asya` pip package

All introspection uses `inspect`, `typing`, and `dataclasses` from the standard library. Pydantic is detected at import time (`try: from pydantic import BaseModel`) but is not required. If Pydantic is not installed and a handler declares a `BaseModel` parameter, the runtime raises a clear startup error.

---

### 6. Handler signature forms

#### 6.1 Legacy dict handler (backward compatible)

```python
def process(payload: dict) -> dict:
    return {"result": payload["text"].upper()}
```

- Single `dict` parameter triggers fallback mode.
- No extraction, no merge -- full payload in, full payload out.
- `ASYA_HANDLER_INPUT` and `ASYA_HANDLER_OUTPUT` are ignored.

#### 6.2 Typed parameters, dict return

```python
def analyze(text: str, language: str = "en") -> dict:
    score = sentiment_analysis(text, language)
    return {"sentiment": score}
```

- Parameters extracted from input path by name.
- Return dict merged at output path.
- `language` is optional (has default).

#### 6.3 Typed parameters, typed return

```python
from pydantic import BaseModel

class AnalysisResult(BaseModel):
    sentiment: float
    confidence: float

def analyze(text: str, language: str = "en") -> AnalysisResult:
    return AnalysisResult(sentiment=0.85, confidence=0.92)
```

- Return value serialized via `.model_dump()`, then merged at output path.

#### 6.4 Pydantic input model

```python
from pydantic import BaseModel

class TextInput(BaseModel):
    text: str
    language: str = "en"
    max_tokens: int = 512

class TextOutput(BaseModel):
    summary: str
    token_count: int

async def summarize(input: TextInput) -> TextOutput:
    result = await llm.summarize(input.text, lang=input.language, max_tokens=input.max_tokens)
    return TextOutput(summary=result.text, token_count=result.tokens)
```

- Parameter `input` is extracted by name from the input subtree: `subtree["input"]`, then deserialized via `TextInput.model_validate()`.
- With `ASYA_HANDLER_INPUT=/`, payload must contain `{"input": {"text": "...", ...}}`.
- With `ASYA_HANDLER_INPUT=/context`, payload must contain `{"context": {"input": {"text": "...", ...}}}`.
- Pydantic validation errors are returned as `processing_error` with the validation detail.

#### 6.5 Multiple typed parameters

```python
async def enrich(text: str, image: ImageModel, temperature: float = 0.7):
    ...
```

- Each parameter extracted individually from input subtree by name.
- `temperature` is optional.
- `image` is deserialized as `ImageModel.model_validate(payload[input_path]["image"])`.

#### 6.6 Dataclass handler

```python
from dataclasses import dataclass

@dataclass
class Config:
    threshold: float = 0.5
    model_name: str = "default"

@dataclass
class Result:
    label: str
    score: float

def classify(config: Config, text: str) -> Result:
    return Result(label="positive", score=0.9)
```

- `config` deserialized via `Config(**value)`.
- Return serialized via `dataclasses.asdict()`.

#### 6.7 TypedDict handler

```python
from typing import TypedDict

class InputData(TypedDict):
    text: str
    metadata: dict

class OutputData(TypedDict):
    result: str
    score: float

def process(data: InputData) -> OutputData:
    return {"result": "ok", "score": 0.95}
```

- Parameter `data` extracted by name from input subtree: `subtree["data"]`.
- TypedDicts are dicts at runtime -- no deserialization needed, direct pass-through.
- Provides IDE autocompletion and type checker support without runtime overhead.

#### 6.8 Class-based handler with typed method

```python
from pydantic import BaseModel

class Prediction(BaseModel):
    label: str
    confidence: float

class Classifier:
    def __init__(self, model_path: str = "/models/default"):
        self.model = load_model(model_path)

    async def predict(self, text: str, top_k: int = 3) -> Prediction:
        result = await self.model.run(text, top_k=top_k)
        return Prediction(label=result.label, confidence=result.score)
```

- Type introspection applies to the method (`predict`), not `__init__`.
- `self` is excluded from parameter extraction.
- `ASYA_HANDLER=module.Classifier.predict`

---

### 7. Yield with typed returns

Generator handlers (sync and async) use `yield` to emit frames. Typed returns work identically to `return` -- the yielded value is serialized and merged at the output path.

#### 7.1 Typed yield downstream

```python
from pydantic import BaseModel

class ChunkResult(BaseModel):
    chunk_id: int
    text: str

def process_chunks(items: list) -> ChunkResult:
    for i, item in enumerate(items):
        yield ChunkResult(chunk_id=i, text=item.upper())
```

Each `yield` serializes `ChunkResult` via `.model_dump()` and merges into `payload[output_path]`.

#### 7.2 Typed yield upstream (partial)

```python
class Token(BaseModel):
    text: str
    index: int

class FinalResult(BaseModel):
    full_text: str
    token_count: int

async def stream_llm(prompt: str) -> FinalResult:
    tokens = []
    async for i, tok in aenumerate(llm.stream(prompt)):
        tokens.append(tok)
        yield Token(text=tok, index=i), True     # upstream partial

    yield FinalResult(full_text="".join(tokens), token_count=len(tokens))
```

- `yield model, True` -- the model is serialized and sent as an upstream partial frame. The partial is merged at the output path in the upstream direction.
- `yield model` (without `True`) -- downstream frame, merged at output path.
- The yield protocol from the original RFC (section 4) is unchanged; only the serialization step is added.

#### 7.3 Mixed yield types

The return type annotation applies to the final downstream yield. Upstream partials may have a different shape (as shown above with `Token` vs `FinalResult`). The runtime does not enforce type consistency across yields -- it serializes whatever is yielded.

---

### 8. Schema generation

Type annotations enable automatic JSON schema generation for gateway tool exposure (MCP tool definitions).

#### Mechanism

At handler load time, the runtime can generate a JSON schema from the handler's input parameters and return type. This schema is made available to the gateway for MCP `tools/list` responses.

```python
# Handler with Pydantic model param:
async def get_weather(request: WeatherRequest) -> WeatherResult:
    ...

# Generated input schema (from param "request" -> WeatherRequest):
{
  "type": "object",
  "properties": {
    "request": {
      "type": "object",
      "properties": {
        "city": {"type": "string"},
        "units": {"type": "string", "default": "metric"}
      },
      "required": ["city"]
    }
  },
  "required": ["request"]
}

# Handler with primitive params:
async def get_weather(city: str, units: str = "metric") -> WeatherResult:
    ...

# Generated input schema (from individual params):
{
  "type": "object",
  "properties": {
    "city": {"type": "string"},
    "units": {"type": "string", "default": "metric"}
  },
  "required": ["city"]
}

# Generated output schema (from WeatherResult, same for both):
{
  "type": "object",
  "properties": {
    "temperature": {"type": "number"},
    "description": {"type": "string"}
  },
  "required": ["temperature", "description"]
}
```

#### Pydantic models

For Pydantic BaseModel parameters, use `.model_json_schema()` (v2) or `.schema()` (v1) directly -- Pydantic already generates JSON Schema.

#### Dataclasses and TypedDicts

For dataclasses and TypedDicts, the runtime walks `__annotations__` and maps Python types to JSON Schema types:

| Python type | JSON Schema type |
|---|---|
| `str` | `string` |
| `int` | `integer` |
| `float` | `number` |
| `bool` | `boolean` |
| `list` / `List[T]` | `array` |
| `dict` / `Dict[K, V]` | `object` |
| `Optional[T]` | nullable `T` |

#### Exposure mechanism

Schema generation is a **read-only introspection** performed once at startup. The schema is stored in memory and served via a dedicated endpoint on the runtime's Unix socket (e.g., `GET /schema`). The sidecar can forward this to the gateway on request.

This is a future integration point -- the initial implementation focuses on the extraction/merge mechanics. Schema serving can be added incrementally.

---

### 9. Configuration

#### Environment variables

| Variable | Default | Description |
|---|---|---|
| `ASYA_HANDLER` | (required) | Handler function path (e.g., `module.function` or `module.Class.method`) |
| `ASYA_HANDLER_INPUT` | `/` | JSONPath-like subpath for parameter extraction from payload |
| `ASYA_HANDLER_OUTPUT` | `/` | JSONPath-like subpath for result merge into payload |

#### Path syntax

- `/` -- payload root (entire payload dict)
- `/key` -- `payload["key"]`
- `/key/subkey` -- `payload["key"]["subkey"]`
- Leading `/` is required. No trailing `/`. No array indexing. No wildcards.

#### Interaction with handler mode

`ASYA_HANDLER_INPUT` and `ASYA_HANDLER_OUTPUT` operate within payload mode. They are orthogonal to message metadata access (`/tmp/msg/` from epic 1ixt). The env var `ASYA_HANDLER_MODE` will be deprecated once epic 1ixt lands (envelope mode is replaced by `/tmp/msg/`), but typed signatures work with both modes during the transition:

- **Payload mode** (default): `ASYA_HANDLER_INPUT` / `ASYA_HANDLER_OUTPUT` apply to the payload dict.
- **Envelope mode**: Not supported with typed signatures. If `ASYA_HANDLER_MODE=envelope` and the handler has typed parameters (not single `dict`), the runtime raises a startup error. Envelope mode is being phased out by epic 1ixt.

#### Deployment examples

**Pydantic model parameter** (`ASYA_HANDLER_INPUT=/`, param name does the key lookup):

```yaml
apiVersion: asya.dev/v1alpha1
kind: AsyncActor
metadata:
  name: weather-actor
spec:
  image: my-handlers:latest
  transport: sqs
  handler: handlers.weather.get_weather  # get_weather(request: WeatherRequest)
  env:
    - name: ASYA_HANDLER_OUTPUT
      value: "/weather"
    # ASYA_HANDLER_INPUT defaults to "/" -- param name "request" selects payload["request"]
```

Payload flow:
```
Input:  {"request": {"city": "Tokyo", "units": "metric"}, "session_id": "abc"}
                          |
                    extract param "request" from /
                    -> payload["request"] = {"city": "Tokyo", "units": "metric"}
                    -> WeatherRequest.model_validate({"city": "Tokyo", "units": "metric"})
                          |
               get_weather(request=WeatherRequest(city="Tokyo", units="metric"))
                          |
                    WeatherResult(temperature=22.5, description="Clear")
                          |
                    merge .model_dump() into /weather
                          |
Output: {"request": {"city": "Tokyo", "units": "metric"}, "session_id": "abc",
         "weather": {"temperature": 22.5, "description": "Clear"}}
```

**Primitive parameters** (same payload, `ASYA_HANDLER_INPUT=/request` to navigate into the subtree):

```yaml
apiVersion: asya.dev/v1alpha1
kind: AsyncActor
metadata:
  name: weather-actor
spec:
  image: my-handlers:latest
  transport: sqs
  handler: handlers.weather.get_weather  # get_weather(city: str, units: str = "metric")
  env:
    - name: ASYA_HANDLER_INPUT
      value: "/request"
    - name: ASYA_HANDLER_OUTPUT
      value: "/weather"
```

Payload flow:
```
Input:  {"request": {"city": "Tokyo", "units": "metric"}, "session_id": "abc"}
                          |
                    navigate to /request subtree
                    -> {"city": "Tokyo", "units": "metric"}
                    extract param "city" -> "Tokyo"
                    extract param "units" -> "metric"
                          |
               get_weather(city="Tokyo", units="metric")
                          |
                    result: 22.5 (float)
                          |
                    write scalar at /weather
                          |
Output: {"request": {"city": "Tokyo", "units": "metric"}, "session_id": "abc",
         "weather": 22.5}
```

---

### 10. Migration and backward compatibility

#### Zero breaking changes

Existing handlers with `payload: dict` signature continue to work without any modification. The single-dict-parameter detection (section 2) ensures full backward compatibility.

| Handler form | ASYA_HANDLER_INPUT | ASYA_HANDLER_OUTPUT | Behavior |
|---|---|---|---|
| `def f(payload: dict) -> dict` | ignored | ignored | Full payload in, full payload out (current behavior) |
| `def f(payload: dict)` | ignored | ignored | Full payload in, None return = abort |
| `def f(text: str) -> dict` | applied | applied | Extract `subtree["text"]` by param name, merge return dict |
| `def f(req: MyModel) -> MyModel` | applied | applied | Extract `subtree["req"]`, validate via `model_validate()`, serialize + merge |

#### Migration path

1. **No action required** for existing `payload: dict` handlers.
2. To adopt typed signatures, change the handler signature and set `ASYA_HANDLER_INPUT` / `ASYA_HANDLER_OUTPUT` in the AsyncActor spec.
3. Handlers can be migrated one actor at a time -- the feature is per-handler, not global.

#### Detection logic

The runtime distinguishes legacy from typed handlers at load time:

```
if len(params) == 1 and annotation in (dict, inspect.Parameter.empty, Dict, Dict[str, Any]):
    -> legacy dict mode (no extraction, no merge)
else:
    -> typed mode (extract by param name, merge at output path)
```

---

### 11. Dependencies

#### Epic 1ixt (message metadata vfs) -- soft dependency

Typed handler signatures are independent of `/tmp/msg/`. They solve orthogonal problems:

- **1ixz** (this epic): payload extraction and result merge via typed function parameters.
- **1ixt**: message metadata access (route, headers) via virtual filesystem.

However, once 1ixt lands and `ASYA_HANDLER_MODE=envelope` is removed, the interaction becomes cleaner: typed signatures always operate on payload, metadata always goes through `/tmp/msg/`. During the transition, typed signatures are only supported in payload mode (section 9).

#### Epic 1irj (flow free vars & iteration) -- no dependency

Flow DSL compilation generates router actors that run in envelope mode. Typed handler signatures apply to leaf actor handlers, not routers. No interaction.

#### Runtime changes

All changes are confined to `src/asya-runtime/asya_runtime.py`. The sidecar, gateway, and injector are unaffected. The runtime remains a single file with no external dependencies (Pydantic is optional, detected if installed by the user's handler code).
