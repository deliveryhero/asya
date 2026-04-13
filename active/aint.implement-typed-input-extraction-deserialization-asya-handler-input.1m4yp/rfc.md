## Status: REJECTED

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

Allow handlers to declare typed input and output parameters that the runtime extracts from (and merges back into) the payload. Mapping between payload locations and handler parameters is controlled by deployment-time environment variables, so the same handler code works across different pipelines without modification.

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

Deployed with `ASYA_PARAMS_AT=.` and `ASYA_RESULT_AT=.weather`, the runtime receives payload:
```json
{"request": {"city": "New York", "units": "metric"}}
```
extracts `request` from payload root (by parameter name), calls the handler, and merges the result into `payload["weather"]`:
```json
{"request": {"city": "New York", "units": "metric"}, "weather": {"temperature": 70, "description": "good weather"}}
```


Or even primitive types (same request/response when deployed with `ASYA_PARAMS_AT=.request` and `ASYA_RESULT_AT=.weather`):

```python
async def get_weather(city: str, units: str = "metric") -> float:
    data = await weather_api.fetch(city, units)
    return data.temp
```


#### Non-goals

- Replacing `/proc/asya/msg/` metadata access (that is epic 1ixt).
- Adding an `asya` pip package or framework-specific imports.
- Loop constructs in flow DSL (that is epic 1irj).
- Changing the sidecar-runtime wire protocol.

---

### 2. Input mapping (`ASYA_PARAMS_AT`)

#### Env var

| Variable | Default | Description |
|---|---|---|
| `ASYA_PARAMS_AT` | `.` | jq-style path from which handler parameters are extracted |

#### Path syntax (reduced jq)

Paths use jq-style dot notation to navigate into the payload. Only single-location
addressing is supported (no wildcards, filters, slicing, or recursive descent).

| Syntax | Meaning | Example |
|--------|---------|---------|
| `.` | Root (whole payload) | `ASYA_PARAMS_AT=.` |
| `.key` | Child access | `.context` = `payload["context"]` |
| `.key.subkey` | Nested access | `.results.nlp` = `payload["results"]["nlp"]` |
| `.[n]` | Array index | `.[0]` = `payload[0]` |
| `.[-1]` | Negative index | `.events[-1]` = last element |
| `.[+]` | Append (write-only) | `.events[+]` = append to array (only valid in `ASYA_RESULT_AT`) |
| Combined | Dot + index | `.events[-1].data` = `payload["events"][-1]["data"]` |

Not supported: `.[*]` (wildcard), `..` (recursive descent), `.[?@.x>1]` (filters), `.[0:5]` (slicing), `.[-]` (use `[+]` for append).

#### Extraction rules

The runtime inspects the handler signature with `inspect.signature()`. For each parameter (excluding `self` for class methods), it looks up a key matching the parameter name within the subtree selected by `ASYA_PARAMS_AT`.

#### `**kwargs` support

If the handler declares `**kwargs`, the runtime passes **all keys** from the input subtree as keyword arguments. Named parameters are extracted first by name; remaining keys go into `**kwargs`.

```python
# ASYA_PARAMS_AT=.  ->  all payload keys passed as kwargs
def handler(**kwargs) -> dict:
    return {"result": kwargs["text"].upper()}
# Payload: {"text": "hello", "lang": "en"}
# Called as: handler(text="hello", lang="en")
```

```python
# Mixed: named param extracted first, rest goes to **kwargs
def handler(text: str, **extra) -> dict:
    return {"result": text.upper(), "extra_keys": list(extra.keys())}
# Payload: {"text": "hello", "lang": "en", "debug": true}
# Called as: handler(text="hello", lang="en", debug=True)
```

#### `*args` is disallowed

Handlers must NOT declare `*args` (variadic positional parameters). JSON objects are unordered -- positional extraction is ambiguous. The runtime raises a **startup error** if `*args` is detected in the handler signature:

```
RuntimeError: Handler 'module.handler' declares *args which is not supported.
JSON objects are unordered; use **kwargs or named parameters instead.
```

**Example: root extraction (`ASYA_PARAMS_AT=.`)**

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

**Example: nested extraction (`ASYA_PARAMS_AT=.context`)**

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

**Example: array access (`ASYA_PARAMS_AT=.events[-1]`)**

```python
def handler(text: str, severity: str):
    ...
```

Payload:
```json
{
  "events": [
    {"text": "first", "severity": "low"},
    {"text": "latest", "severity": "high"}
  ]
}
```

Runtime navigates to `payload["events"][-1]` (last element), then extracts `text` and `severity` from it.

#### Missing keys

If a required parameter (no default value) is missing from the input subtree, the runtime returns a `processing_error` to the sidecar with a descriptive message listing the missing parameter name and the input path.

Optional parameters (those with defaults in the signature) are omitted from extraction when the key is absent, and the handler receives the default value.

#### Uniform extraction (no special-casing)

All parameters are extracted by name, regardless of type annotation. A parameter
annotated as `dict` is treated the same as `str` or `BaseModel` -- the runtime
looks up `subtree[param_name]` and passes whatever JSON value is there.

```python
# Parameter "data" of type dict -- extracted by name like any other param
# ASYA_PARAMS_AT=.  ->  payload["data"] is passed as the argument
def handler(data: dict) -> dict:
    return {"result": data["text"].upper()}
```

There is no legacy fallback mode. The type annotation controls deserialization
(e.g., Pydantic validation), not whether extraction happens.

---

### 3. Output mapping (`ASYA_RESULT_AT`)

#### Env var

| Variable | Default | Description |
|---|---|---|
| `ASYA_RESULT_AT` | `.` | jq-style path where handler result is merged into payload |

#### Merge target

The handler's return value (serialized to `dict` if it is a model) is merged into the payload at the path specified by `ASYA_RESULT_AT`.

**Example: root output (`ASYA_RESULT_AT=.`)**

```python
def handler(text: str) -> dict:
    return {"sentiment": "positive", "score": 0.95}
```

Before: `{"text": "great", "lang": "en"}`
After: `{"text": "great", "lang": "en", "sentiment": "positive", "score": 0.95}`

**Example: nested output (`ASYA_RESULT_AT=.analyzed`)**

Same handler, same return value.

Before: `{"text": "great", "lang": "en"}`
After: `{"text": "great", "lang": "en", "analyzed": {"sentiment": "positive", "score": 0.95}}`

**Example: deep nested output (`ASYA_RESULT_AT=.results.nlp`)**

Before: `{"text": "great", "results": {"vision": {...}}}`
After: `{"text": "great", "results": {"vision": {...}, "nlp": {"sentiment": "positive", "score": 0.95}}}`

Intermediate dicts are created automatically if they do not exist.

#### `None` return

If the handler returns `None`, the payload is left unchanged and the message is routed to `x-sink` (abort semantics, same as today).

---

### 4. Merge semantics

When the handler returns a dict-like result, the runtime merges it into the payload at the output path. The merge strategy is configurable via `ASYA_RESULT_MERGE`.

#### Env var

| Variable | Default | Description |
|---|---|---|
| `ASYA_RESULT_MERGE` | `shallow` | Merge strategy: `shallow` or `deep` |

#### Shallow merge (default)

`ASYA_RESULT_MERGE=shallow` -- performs `target.update(result)` at the output path:

1. The return value is serialized to a `dict` (via `.model_dump()`, `dataclasses.asdict()`, or `dict()` depending on type).
2. Each top-level key in the result dict is written into the target subtree.
3. Keys present in the target but absent from the result are **preserved** (not deleted).
4. Keys present in both are **overwritten** by the result (including nested dicts -- they are replaced, not recursively merged).

**Example** (output path: `.analyzed`):

Target before: `{"analyzed": {"foo": "bar", "baz": "zoo", "nested": {"a": 1, "b": 2}}}`
Handler returns: `{"foo": "kek", "new_field": 42, "nested": {"a": 99}}`
Target after: `{"analyzed": {"foo": "kek", "baz": "zoo", "nested": {"a": 99}, "new_field": 42}}`

Note: `nested.b` is lost because shallow merge replaces the entire `nested` dict.

#### Deep merge

`ASYA_RESULT_MERGE=deep` -- recursively merges nested dicts:

1. Same serialization as shallow.
2. For each key in the result: if both the target and result values are dicts, merge recursively. Otherwise, overwrite.
3. Non-dict values (lists, scalars) are always overwritten, never merged.

**Example** (same data as above):

Target before: `{"analyzed": {"foo": "bar", "baz": "zoo", "nested": {"a": 1, "b": 2}}}`
Handler returns: `{"foo": "kek", "new_field": 42, "nested": {"a": 99}}`
Target after: `{"analyzed": {"foo": "kek", "baz": "zoo", "nested": {"a": 99, "b": 2}, "new_field": 42}}`

Note: `nested.b` is preserved because deep merge recurses into nested dicts.

#### When to use each

- **Shallow** (default): Predictable, matches `dict.update()` semantics. Use when each actor owns its output subtree and doesn't need to preserve nested structure from previous actors.
- **Deep**: Use when multiple actors write to overlapping nested structures and must preserve each other's keys.

#### Scalar returns

If the handler's return type annotation is a scalar (e.g., `-> str`, `-> int`, `-> float`, `-> bool`), the runtime writes the value directly at the output path rather than merging:

```python
def classify(text: str) -> str:
    return "positive"
```

With `ASYA_RESULT_AT=.sentiment`:

Before: `{"text": "great"}`
After: `{"text": "great", "sentiment": "positive"}`

#### List returns

Similarly, `-> list` or `-> List[...]` writes the list directly at the output path, no merge.

#### Array append (`[+]`)

If `ASYA_RESULT_AT` ends with `[+]`, the runtime appends the handler's return value to the array at the parent path instead of overwriting:

```python
def process_event(text: str) -> dict:
    return {"text": text, "status": "processed"}
```

With `ASYA_RESULT_AT=.events[+]`:

Before: `{"events": [{"text": "old", "status": "done"}]}`
After: `{"events": [{"text": "old", "status": "done"}, {"text": "hello", "status": "processed"}]}`

If the target path does not exist, the runtime creates an empty list and appends. If the target exists but is not a list, the runtime returns a `processing_error`.

`[+]` is **write-only** -- using it in `ASYA_PARAMS_AT` raises a startup error.

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

#### 6.1 Dict parameter (uniform extraction)

```python
# ASYA_PARAMS_AT=.  ->  extracts payload["data"]
def process(data: dict) -> dict:
    return {"result": data["text"].upper()}
```

- Parameter `data` extracted by name from input subtree, same as any other type.
- No special-casing -- `dict` is just another annotation.
- `ASYA_PARAMS_AT` and `ASYA_RESULT_AT` apply normally.

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
- With `ASYA_PARAMS_AT=.`, payload must contain `{"input": {"text": "...", ...}}`.
- With `ASYA_PARAMS_AT=.context`, payload must contain `{"context": {"input": {"text": "...", ...}}}`.
- Pydantic validation errors are returned as `processing_error` with the validation detail.

#### 6.5 Multiple typed parameters

```python
async def enrich(text: str, image: ImageModel, temperature: float = 0.7):
    ...
```

- Each parameter extracted individually from input subtree by name.
- `temperature` is optional.
- `image` is deserialized as `ImageModel.model_validate(subtree["image"])`.

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

#### 6.8 `**kwargs` handler (whole subtree)

```python
# ASYA_PARAMS_AT=.context  ->  all keys from payload["context"] as kwargs
def process(**kwargs) -> dict:
    return {"result": kwargs["text"].upper(), "lang": kwargs.get("lang", "en")}
```

- Receives all keys from the input subtree as keyword arguments.
- Useful for migration from legacy `payload: dict` handlers.
- Can be mixed with named params: `def f(text: str, **rest)`.

#### 6.9 Class-based handler with typed method

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

Each `yield` serializes `ChunkResult` via `.model_dump()` and merges into payload at `ASYA_RESULT_AT`.

#### 7.2 Typed yield upstream (partial)

Upstream partials use the existing `{"partial": True}` convention. For typed
handlers, the model must be serialized to dict and merged with
`{"partial": True}` before yielding:

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
        yield {"partial": True, "text": tok, "index": i}  # upstream partial

    yield FinalResult(full_text="".join(tokens), token_count=len(tokens))
```

- `yield {"partial": True, ...}` -- dict with `"partial"` key is forwarded upstream to the gateway. The runtime strips the `"partial"` key before forwarding.
- `yield model` (without `"partial"`) -- downstream frame, serialized and merged at output path.
- The yield protocol is unchanged from the existing convention; only the serialization step for non-partial yields is added.

#### 7.3 Mixed yield types

The return type annotation applies to the final downstream yield. Upstream partials are always raw dicts with `"partial": True`. The runtime does not enforce type consistency across yields -- it serializes whatever is yielded (typed models are serialized, dicts are passed through).

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
| `ASYA_PARAMS_AT` | `.` | jq-style path for parameter extraction from payload |
| `ASYA_RESULT_AT` | `.` | jq-style path for result merge into payload |
| `ASYA_RESULT_MERGE` | `shallow` | Merge strategy: `shallow` (dict.update) or `deep` (recursive) |

#### Path syntax (reduced jq)

Uses jq-style dot notation. Only single-location addressing is supported.

- `.` -- payload root (entire payload dict)
- `.key` -- `payload["key"]`
- `.key.subkey` -- `payload["key"]["subkey"]`
- `.[0]` -- `payload[0]` (array index)
- `.[-1]` -- last element (negative index)
- `.[+]` -- append to array (write-only, only valid in `ASYA_RESULT_AT`)
- `.events[-1].data` -- combined navigation

Not supported: wildcards (`.[*]`), recursive descent (`..`), filters (`.[?@.x>1]`), slicing (`.[0:5]`), `.[-]` (use `[+]`).

#### Interaction with metadata VFS

`ASYA_PARAMS_AT` and `ASYA_RESULT_AT` operate on the payload dict. They are orthogonal to message metadata access (`/proc/asya/msg/` from epic 1ixt):

- **Typed signatures** (this epic): payload extraction and result merge via function parameters.
- **Metadata VFS** (epic 1ixt): message metadata (route, headers, status) via virtual filesystem.

The two features solve different problems and do not interact. Typed signatures always operate on payload; metadata always goes through `/proc/asya/msg/`.

#### Deployment examples

**Pydantic model parameter** (`ASYA_PARAMS_AT=.`, param name does the key lookup):

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
    - name: ASYA_RESULT_AT
      value: ".weather"
    # ASYA_PARAMS_AT defaults to "." -- param name "request" selects payload["request"]
```

Payload flow:
```
Input:  {"request": {"city": "Tokyo", "units": "metric"}, "session_id": "abc"}
                          |
                    extract param "request" from .
                    -> payload["request"] = {"city": "Tokyo", "units": "metric"}
                    -> WeatherRequest.model_validate({"city": "Tokyo", "units": "metric"})
                          |
               get_weather(request=WeatherRequest(city="Tokyo", units="metric"))
                          |
                    WeatherResult(temperature=22.5, description="Clear")
                          |
                    merge .model_dump() into .weather
                          |
Output: {"request": {"city": "Tokyo", "units": "metric"}, "session_id": "abc",
         "weather": {"temperature": 22.5, "description": "Clear"}}
```

**Primitive parameters** (same payload, `ASYA_PARAMS_AT=.request` to navigate into the subtree):

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
    - name: ASYA_PARAMS_AT
      value: ".request"
    - name: ASYA_RESULT_AT
      value: ".weather"
```

Payload flow:
```
Input:  {"request": {"city": "Tokyo", "units": "metric"}, "session_id": "abc"}
                          |
                    navigate to .request subtree
                    -> {"city": "Tokyo", "units": "metric"}
                    extract param "city" -> "Tokyo"
                    extract param "units" -> "metric"
                          |
               get_weather(city="Tokyo", units="metric")
                          |
                    result: 22.5 (float)
                          |
                    write scalar at .weather
                          |
Output: {"request": {"city": "Tokyo", "units": "metric"}, "session_id": "abc",
         "weather": 22.5}
```

**Array access** (process last event from a list):

```yaml
apiVersion: asya.dev/v1alpha1
kind: AsyncActor
metadata:
  name: event-analyzer
spec:
  image: my-handlers:latest
  transport: sqs
  handler: handlers.events.analyze  # analyze(text: str, severity: str) -> AnalysisResult
  env:
    - name: ASYA_PARAMS_AT
      value: ".events[-1]"
    - name: ASYA_RESULT_AT
      value: ".analysis"
```

---

### 10. Migration and backward compatibility

#### Uniform model (no legacy detection)

There is no legacy/typed mode distinction. All handlers use the same extraction
and merge logic. The parameter name is always used as the key for extraction,
regardless of the type annotation.

| Handler form | ASYA_PARAMS_AT | ASYA_RESULT_AT | Behavior |
|---|---|---|---|
| `def f(data: dict) -> dict` | applied | applied | Extract `subtree["data"]` by param name, merge return dict |
| `def f(text: str) -> dict` | applied | applied | Extract `subtree["text"]` by param name, merge return dict |
| `def f(req: MyModel) -> MyModel` | applied | applied | Extract `subtree["req"]`, validate via `model_validate()`, serialize + merge |
| `def f(a: str, b: int) -> dict` | applied | applied | Extract `subtree["a"]` and `subtree["b"]` by param names |
| `def f(**kwargs) -> dict` | applied | applied | Pass all keys from subtree as keyword arguments |
| `def f(text: str, **rest)` | applied | applied | Extract `subtree["text"]`, remaining keys go to `**rest` |
| `def f(*args)` | **error** | -- | Startup error: `*args` disallowed (ambiguous ordering) |

#### Migration path for existing `payload: dict` handlers

Existing handlers that use the convention `def f(payload: dict) -> dict` will
need a minor change. With uniform extraction, the runtime extracts
`subtree["payload"]` (by parameter name), which is likely not what was intended.

**Option A**: Rename the parameter to match the actual payload key:
```python
# Before: def process(payload: dict) -> dict
# After:  parameter name matches the key in the payload
def process(data: dict) -> dict:
    return {"result": data["text"].upper()}
# Payload: {"data": {"text": "hello"}}
```

**Option B**: Use `**kwargs` to receive all keys from the subtree:
```python
def process(**kwargs) -> dict:
    return {"result": kwargs["text"].upper()}
# Payload: {"text": "hello"}, ASYA_PARAMS_AT=.
```

Handlers can be migrated one actor at a time -- the feature is per-handler, not global.

---

### 11. Dependencies

#### Epic 1ixt (message metadata vfs) -- no dependency

Typed handler signatures are independent of `/proc/asya/msg/`. They solve orthogonal problems:

- **1ixz** (this epic): payload extraction and result merge via typed function parameters.
- **1ixt**: message metadata access (route, headers) via virtual filesystem.

Typed signatures operate on payload; metadata goes through `/proc/asya/msg/`. No interaction.

#### Epic 1irj (flow free vars & iteration) -- no dependency

Flow DSL compilation generates router actors. Typed handler signatures apply to leaf actor handlers, not routers. No interaction.

#### Runtime changes

All changes are confined to `src/asya-runtime/asya_runtime.py`. The sidecar, gateway, and injector are unaffected. The runtime remains a single file with no external dependencies (Pydantic is optional, detected if installed by the user's handler code).
