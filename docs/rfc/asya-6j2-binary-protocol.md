## 1. Competitive Analysis of Binary Formats

To replace JSON, we evaluated formats based on the requirement for **variable fields (no fixed schema)** and **Python/Go interoperability**.

| Format          | Pros                                                                            | Cons                                                                                          |
| --------------- | ------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| **MessagePack** | 1:1 JSON mapping, extremely popular, fast.                                      | Requires external library in Python (`pip install`).                                          |
| **CBOR**        | IETF Standard, handles binary blobs natively.                                   | Similar to MessagePack; requires external Python lib.                                         |
| **Protobuf**    | Smallest/Fastest.                                                               | **Incompatible** with Asya's requirement for variable/dynamic fields without high complexity. |
| **Marshal**     | Built into Python core (no `pip`). Fastest possible deserialization for Python. | Python-specific; version-dependent; requires custom Go encoder.                               |
|                 |                                                                                 |                                                                                               |

---

## 2. The Bottleneck: Double Deserialization

Currently, the Go sidecar must deserialize the entire JSON blob to find the `route` key, then the Python runtime must deserialize the entire blob again to use the `payload`.

## 3. The "No-Pip" Constraint: Evaluated Strategies

Since `asya.sh` must run on any user image without requiring `pip install msgpack`, we analyzed three creative deployment paths:
* **The FFI Hack (Go `.so`):**
	* Instead of Python decoding the MessagePack, your **Go Sidecar** provides a small Shared Object (`.so`) file.
	* **The Idea:** You compile a small Go function into a C-shared library (`asya_codec.so`) using `-buildmode=c-shared`.
	- **The Mount:** You mount this `.so` file into the container along with `asya_runtime.py`.
	- **The Python Side:** Python uses the built-in `ctypes` library (which is in the Standard Library) to call the Go function.
	- **Why it's fast:** You are using Go's highly optimized MessagePack/CBOR parsers. Python just receives a pointer to the data.
	- **Why it's hidden:** No `pip install`. `ctypes` is always there.
	* **PROBLEMS**:
		* **The GLIBC Trap:** This is the biggest risk. If you compile the `.so` on a Debian-based system (GLIBC) and the user runs an Alpine-based image (musl), the library **will not load**.
		* **Memory Management:** Passing strings/bytes between Go and C (Python) requires careful manual memory freeing (`C.free`) to avoid leaks.
	* **REJECTED.**
* **Library Mounting:** Injecting a pure-python `msgpack` source folder via K8s volume and modifying `sys.path`. **FEASIBLE, but lower performance and not want to modify python environment without users permission.**
* **The Marshal-Handshake (The "Native" Path):** Using Python’s built-in `marshal` module. **PROPOSED.**

---
## 4. Proposed Solution: The Marshal-Handshake Protocol

This solution achieves C-level performance using only the Python Standard Library.
### Phase A: The Version-Aware Handshake

Because `marshal` can change between Python versions, the connection begins with a negotiation:
1. **Runtime Initialization:** `asya_runtime.py` identifies its internal format version: `v = marshal.version`.
2. **The Handshake:** Python sends a "Ready" message: `READY|MARSHAL|V4`.
3. **Sidecar Adaptation:** The Go sidecar configures its encoder to match that specific version for the duration of the session.
### Phase B: Binary Streaming
* **Encoding:** The Go sidecar uses a custom `go-marshal` encoder to wrap messages.
* **Decoding:** Python receives the bytes and calls `marshal.loads(stream)`. This is roughly **5x–10x faster** than `json.loads()` because it maps directly to internal C-structures of Python objects.
### Limitations & Risks
* **Maintenance:** We must maintain the Go implementation of the Python Marshal format.
* **Type Safety:** ⚠️ `marshal` supports primary types (dict, list, str, bytes, float). Custom user classes must be converted to dicts before transit (standard for actor meshes).
* **Interoperability:** This approach is optimized for Go  Python. If we add a Rust or JS runtime later, they will need their own "Native" format or a fallback to MessagePack.

---
## 5. Summary of Implementation Steps

1. **Go:** Implement a minimal `marshal` encoder in the sidecar.
2. **Runtime:** Update `asya_runtime.py` to perform the `marshal.version` handshake.
3. **Sidecar:** Implement "Early Exit" decoding logic to extract `route` from the binary stream without touching the `payload` bytes.


---

This extended technical specification is designed to be fed into an LLM or a development team to implement the feature. It focuses on the **Go Sidecar** (Source) and the **Python Runtime** (Sink).

# Technical Spec: Asya Binary Protocol (Marshal-Handshake)

## 1. Objective
Replace JSON messaging between the Go sidecar and Python runtime with a binary protocol leveraging Python’s built-in `marshal` module. This eliminates the need for `pip install` while achieving near-native deserialization speeds.

## 2. Protocol Handshake
Upon actor startup, the Python runtime must negotiate the protocol version to ensure compatibility with the Go sidecar.

### Python Implementation (`asya_runtime.py`)

```python
import marshal
import sys
import socket

def handshake(sock):
    # Detect internal marshal version (usually 4 for Python 3.4+)
    m_version = marshal.version
    py_version = f"{sys.version_info.major}.{sys.version_info.minor}"

    # Send handshake: FORMAT|MARSHAL_VER|PYTHON_VER
    handshake_msg = f"ASYA_INIT|MARSHAL|{m_version}|{py_version}\n"
    sock.sendall(handshake_msg.encode())

    # Wait for ACK from Sidecar
    response = sock.recv(1024).decode()
    return response == "ASYA_ACK"
```

---

## 3. The Go Sidecar: Partial Decoding & Marshal Encoding

The sidecar must extract `route` without fully decoding the `payload` to avoid the "double-parsing" penalty.

### 3.1 Partial Decoding (The "Header Peek")

Since we enforce that `route` is the first key in the map, the Go sidecar uses a streaming reader.
```go
// Simplified logic for extracting route from a MessagePack-like stream
func ExtractRoute(data []byte) (Route, []byte, error) {
    // 1. Read the map header
    // 2. Read the first key. If it is "route", decode the value.
    // 3. Return the Route object and the remaining raw bytes (the payload).
}
```

### 3.2 Go-to-Python Marshal Encoder

Since no official library exists, the Go sidecar implements a minimal encoder for the Python 3.4+ Marshal format (Version 4).

```go
// Internal Go logic to write Python-compatible binary types
func EncodeMarshal(v interface{}) ([]byte, error) {
    var buf bytes.Buffer
    switch val := v.(type) {
    case string:
        buf.WriteByte('s') // Type code for string
        binary.Write(&buf, binary.LittleEndian, int32(len(val)))
        buf.WriteString(val)
    case map[string]interface{}:
        buf.WriteByte('{') // Type code for dict
        for k, v := range val {
            // Recursive encoding...
        }
        buf.WriteByte('0') // Dict terminator
    // Handle: int (i), float (f), list ([), etc.
    }
    return buf.Bytes(), nil
}
```

---

## 4. Efficient Runtime Ingestion

The Python runtime receives binary data directly into a memory buffer and loads it instantly.

### Python Message Loop

```python
def message_loop(sock):
    while True:
        # Read message length header (4 bytes)
        raw_size = sock.recv(4)
        if not raw_size: break
        size = int.from_bytes(raw_size, "little")

        # Read the binary blob
        binary_data = sock.recv(size)

        # Immediate conversion to Python Dict (No string parsing)
        message = marshal.loads(binary_data)

        # Process actor logic
        actor_process(message['payload'])
```

---

## 5. Summary of Tradeoffs & Breakpoints

|**Feature**|**Detail**|
|---|---|
|**Performance**|**High.** `marshal.loads` is implemented in C and is the fastest path to object creation in Python.|
|**Dependency**|**Zero.** Uses only standard `marshal`, `sys`, and `socket` modules.|
|**Breakpoint**|**Schema Evolution.** `marshal` is for data, not classes. Actors must pass "plain old data" (dicts/lists).|
|**Risk**|**Go Maintenance.** The Go sidecar must be updated if Python introduces a "Version 5" marshal format in the future.|

## 6. Proposed Implementation Logic for LLM Generation

"Generate a Go package that implements the Python 3.4+ Marshal Version 4 serialization format. It must support `TYPE_DICT`, `TYPE_LIST`, `TYPE_UNICODE`, and `TYPE_INT`. Pair this with a Python script that uses the `marshal` module to decode these bytes over a Unix Domain Socket, including a version-check handshake."

---


# RISKS

The stability of Python's `marshal` is a bit of a paradox: it is technically "unstable" and "undocumented," yet in practice, it is one of the most reliable parts of the Python core.

To answer your question directly: **If the Sidecar and Runtime agree on Version 3 (or 4), the probability of a decoding failure is near zero.** However, the "stability" risk isn't in the version number itself, but in the **implementation of the types.**

---

### 1. The Stability of Marshal Versions

The `marshal` format is tied to the Python bytecode version. It only changes when Python needs to support a new internal data type (like a new type of constant).

* **Version 2:** Python 2.4+
* **Version 3:** Python 3.2+ (added support for `set` and `frozenset`)
* **Version 4:** Python 3.4+ (added support for binary floating point and specialized strings)
* **Version 5:** Python 3.13+ (added support for more complex object types)

Because `asya.sh` will likely only be passing **Strings, Floats, Ints, Lists, and Dicts**, you are using a subset of the format that has been frozen since the late 2000s.

---

### 2. The Probability of "Agreement without Compatibility"

If your handshake succeeds and both agree on `Version 4`, a "Runtime Error" can only occur in three specific scenarios:

#### A. The "Float" Precision Trap

Python's `marshal` stores floats as binary data. If your Go sidecar uses a math library with slightly different IEEE-754 rounding than the Python runtime's C-compiled `double`, you could technically see a precision mismatch.

* **Probability:** High for extreme precision AI weights, but low for general messaging.
* **Result:** Data is decoded, but the value is slightly off.

#### B. Character Encoding (The UTF-8 Breach)

In Marshal Version 4, strings are expected to be valid UTF-8. If your Go sidecar pushes raw "garbage" bytes into a string field instead of a bytes field, `marshal.loads()` in Python will throw a `UnicodeDecodeError`.

* **Probability:** Moderate (if users handle raw binary as strings).
* **Result:** **Total Failure.** Python crashes during decoding.

#### C. The "Go-Side" Implementation Drift

This is the most likely failure point. Since you are writing a **custom Go encoder** to mimic Python's `marshal.c`, the risk isn't in Python—it's in the Go code. If your Go encoder incorrectly calculates the length prefix for a dictionary, Python will read too many (or too few) bytes and lose its place in the stream.

---

### 3. Comparison of Failure Modes

| Risk Factor | JSON | MessagePack | Marshal (Proposed) |
| --- | --- | --- | --- |
| **Parsing Failure** | Rare (Malformed JSON) | Very Rare (Library Bug) | **Medium** (Go Encoder bug) |
| **Type Mismatch** | High (e.g., Float vs Int) | Low | **Zero** (1:1 with Python types) |
| **Version Conflict** | Zero | Low | **Medium** (Handshake required) |

---

### 4. Making it "Bulletproof" for asya.sh

To move the probability of failure from "low" to "zero," follow these three rules in the **asya** implementation:

1. **Restrict the Vocabulary:** Only implement Go-encoders for `Dict`, `List`, `Unicode`, `Long`, and `Float`. Do not attempt to support `Sets` or `Frozensets`.
2. **String vs Bytes:** Always use `TYPE_ASCII` or `TYPE_UNICODE` for keys and `TYPE_STRING` (raw bytes) for the actual AI `payload`.
3. **The "Safety Valve":** If the handshake reveals a Python version your Go sidecar doesn't recognize (e.g., Python 3.16 in the year 2028), the sidecar must force a fallback to **JSON** (or force users to install `msgpack-python` pip package).

### Summary for your Memo

> "While `marshal` is technically an internal Python format, its core types (Dict/List/String) are effectively frozen. Compatibility risks are negligible provided the Go sidecar accurately implements the length-prefixing logic of the agreed-upon version."


----

# ALTERNATIVE - CUSTOM BINARY FORMAT

This is the "Zero-Trust/Zero-Overhead" approach. By creating a custom framing protocol, you essentially turn **asya.sh** into a high-performance streaming engine. You are effectively building a **Type-Length-Value (TLV)** framing system.

If you go this route, you move away from the limitations of MQ headers (like SQS's 10-attribute limit) while still keeping the performance of a raw binary passthrough.

---

### 1. The Strategy: The "Enveloped" Binary Stream

Instead of relying on the MQ to handle your headers, you treat the entire message body as a single binary blob with a strict internal structure.

**Proposed Format: The "Asya Frame"**

```text
[Magic Byte (1)] [Header Length (4)] [Header (N)] [Payload (M)]

```

* **Magic Byte:** A single byte (e.g., `0xA5`) to identify it as an Asya Frame.
* **Header Length:** A 4-byte unsigned integer (Little Endian) telling the sidecar exactly how many bytes to read for the metadata.
* **Header:** The `route` and `metadata`, encoded in **MessagePack** (for Go/Python cross-compatibility).
* **Payload:** The raw, untouched AI data (images, tensors, etc.), which could be **Marshal** encoded for the Python runtime.

---

### 2. Why this is superior to "Header|Delimiter|Body"

A **Delimiter** (like `\n` or `---`) is dangerous in binary protocols. If your payload (e.g., a PNG or a Pickled tensor) accidentally contains the same byte sequence as your delimiter, the parser will break.

**Length-prefixing (Header Size | Header | Body)** is the industry standard (used by Protobuf and Kafka) because:

1. **O(1) Seeking:** The sidecar reads exactly 4 bytes, knows exactly where the header ends, and knows exactly where the payload begins.
2. **Binary Safety:** The payload can contain any byte sequence without escaping.
3. **Heterogeneous Encoding:** You can use MessagePack for the Header (so the Go sidecar can read it easily) and Marshal for the Body (so the Python runtime can ingest it instantly).

---

### 3. Comparison of Custom Framing vs. MQ Headers

| Feature                | MQ Native Headers          | Custom Framing (Your Idea)           |
| ---------------------- | -------------------------- | ------------------------------------ |
| **Portability**        | Hard (SQS vs Kafka differ) | **Universal** (It's just "the body") |
| **Size Limits**        | Restrictive (SQS 256KB)    | **Unlimited** (Up to the MQ limit)   |
| **Sidecar Complexity** | Low                        | Low-Medium (Slice arithmetic)        |
| **Payload Integrity**  | High                       | **Highest** (Binary transparent)     |

---

### 4. Implementation Code Snippets

#### The Go Sidecar: "The Surgical Slice"

The sidecar doesn't even need a MessagePack library for the payload. It just slices the byte array.

```go
func Unframe(data []byte) (*Route, []byte, error) {
    if data[0] != 0xA5 {
        return nil, nil, errors.New("invalid magic byte")
    }

    // 1. Read Header Length (bytes 1 to 5)
    headerLen := binary.LittleEndian.Uint32(data[1:5])

    // 2. Extract Header Bytes
    headerStart := 5
    headerEnd := 5 + int(headerLen)
    headerBytes := data[headerStart:headerEnd]

    // 3. Decode Route (Go needs to know where to send it)
    var route Route
    msgpack.Unmarshal(headerBytes, &route)

    // 4. THE MAGIC: Extract Payload without copying or decoding
    // We just return a slice of the original buffer
    payloadBytes := data[headerEnd:]

    return &route, payloadBytes, nil
}

```

#### The Python Runtime: "The Marshal Leap"

The runtime receives the `payloadBytes` and immediately jumps into the Python C-structs.

```python
import marshal

# The Go sidecar sends ONLY the payloadBytes over the Unix Socket
def on_receive(raw_payload):
    # This is blindingly fast. No string parsing, no header stripping.
    data = marshal.loads(raw_payload)
    return data

```

---

### 5. Final Critical Verdict for asya.sh

**This is the best solution proposed so far.** By using **Length-Prefixed Framing (Header_Size | Header | Body)**:

1. **You are Transport-Agnostic:** Whether you use SQS, Kafka, or NATS, the logic remains identical.
2. **You solve the "Double Serialization":** The sidecar only parses the tiny header.
3. **You solve the "No-Pip" issue:** The Header uses MessagePack (which you vendor/mount), and the Body uses `marshal` (which is native).
4. **You are future-proof:** You can add a `Protocol_Version` byte to the header later if you need to change formats.

# RISKS OF CUSTOM BINARY FORMAT:

Building a custom framing protocol (e.g., `[Magic][Len][Header][Body]`) is the "pro-tier" way to handle high-performance messaging, but it moves the responsibility of **data integrity** and **safety** from the message broker directly onto your code.

As the maintainer of **asya.sh**, you should consider these four critical risks before committing this to your main branch.

---

### 1. The "OOM" (Out of Memory) Vulnerability

In length-prefixed protocols, the sidecar reads the 4-byte `header_size` and immediately trusts it.

* **The Risk:** If a message is corrupted or a malicious actor pushes a packet with a `header_size` set to **2GB**, your Go sidecar might attempt to allocate a massive buffer before reading the rest of the message.
* **The Fix:** You **must** implement a `MAX_HEADER_SIZE` (e.g., 1MB) limit in the Go sidecar. If the incoming size exceeds this, drop the message immediately.

### 2. "The Black Box" Problem (Observability)

JSON is "human-debuggable." You can look at a message in the SQS or RabbitMQ console and instantly see the routing info.

* **The Risk:** Once you move to `0xA5 [Binary]`, your infrastructure becomes a black box. If an actor is misrouting, SREs cannot troubleshoot the queue directly.
* **The Fix:** You will need to build an `asya-cli decode` tool that can take a raw hex string from a queue and pretty-print the Asya frame for debugging.

### 3. The "Off-by-One" Fragility

Custom binary protocols are notoriously sensitive to "slice logic" errors.

* **The Risk:** If your Go sidecar expects **Little Endian** for the length prefix but a user’s custom actor (perhaps written in another language) sends **Big Endian**, the sidecar will miscalculate the boundary, treating half of the header as the payload.
* **The Fix:** Strictly enforce a single endianness (usually Little Endian for AI/ML workloads) and use a "Magic Byte" at the start to validate that you are indeed looking at a valid Asya frame before parsing.

### 4. Marshalling & Deserialization Attacks

While `marshal` is incredibly fast, it is **not secure** against untrusted data.

* **The Risk:** If an attacker gains access to your Message Queue (SQS/Kafka), they can inject a malicious `marshal` blob. When your Python actor calls `marshal.loads()`, it could potentially execute code or crash the runtime.
* **The Fix:** Since `asya.sh` runs inside a trusted K8s namespace, this is often "accepted risk," but you should warn users: **Never use the Marshal-based binary protocol for messages coming from external/untrusted public internet sources.**

---

### Comparison of Risks vs. Rewards

| Risk | Impact | Mitigation in `asya.sh` |
| --- | --- | --- |
| **OOM/Crash** | High | Hard-coded `MAX_HEADER_SIZE`. |
| **Debuggability** | Medium | `asya-cli` inspector tool. |
| **Compatibility** | Low | Strong "Handshake" at startup. |
| **Security** | Medium | Limit binary protocol to internal-only VPC traffic. |

### Final Memo Summary Recommendation

The **Length-Prefixed Framing** is the best technical choice for `asya.sh`. It is the only way to achieve true **O(1) routing** without double-serialization. The risks are engineering challenges (buffer limits and CLI tools) rather than architectural flaws.
