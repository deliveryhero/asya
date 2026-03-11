"""
Tests for fan-out agentic flows: parallel_sectioning and map_reduce.

Fan-out handlers emit MULTIPLE downstream frames — one per parallel branch.
These tests demonstrate that result.frames (not result.payload) is the
correct API for fan-out scenarios.

Covers:
- parallel_sectioning: preprocessor, 3 specialist stubs, aggregator, full flow
- map_reduce: splitter, chunk_processor, reducer, full flow
- compiled fanout routers: multi-frame output + GET via get_responses
"""

from map_reduce import (
    chunk_processor,
    map_reduce,
    reducer,
    splitter,
)
from parallel_sectioning import (
    aggregator,
    entity_recognizer,
    parallel_sectioning,
    preprocessor,
    sentiment_analyzer,
    topic_extractor,
)


# ── parallel_sectioning: handler stubs (all return single frames) ─────────────


async def test_preprocessor_normalises_text(run_handler):
    state = {"raw_text": "  Hello world\n\nSecond para  "}
    result = await run_handler(preprocessor(state))

    payload = result.payload
    assert payload["text"] == "Hello world\nSecond para"
    assert payload["word_count"] == 4
    assert payload["char_count"] == len(payload["text"])


async def test_preprocessor_falls_back_to_text_key(run_handler):
    state = {"text": "already clean"}
    result = await run_handler(preprocessor(state))
    assert result.payload["text"] == "already clean"


async def test_sentiment_analyzer_returns_sentiment(run_handler):
    result = await run_handler(sentiment_analyzer("some text"))

    payload = result.payload
    assert payload["sentiment"] in {"positive", "negative", "neutral"}
    assert 0.0 <= payload["confidence"] <= 1.0
    assert isinstance(payload["highlights"], list)


async def test_topic_extractor_returns_topics(run_handler):
    result = await run_handler(topic_extractor("some text"))

    payload = result.payload
    assert "topics" in payload
    assert "keywords" in payload
    assert len(payload["topics"]) > 0


async def test_entity_recognizer_returns_entities(run_handler):
    result = await run_handler(entity_recognizer("some text"))

    payload = result.payload
    assert "entities" in payload
    for entity in payload["entities"]:
        assert "text" in entity
        assert "type" in entity


async def test_aggregator_merges_three_analysis_results(run_handler):
    state = {
        "word_count": 42,
        "analysis": [
            {"sentiment": "positive", "confidence": 0.9, "highlights": ["great"]},
            {"topics": ["ai"], "keywords": ["ml"]},
            {"entities": [{"text": "Google", "type": "ORG"}]},
        ],
    }
    result = await run_handler(aggregator(state))

    merged = result.payload["merged_result"]
    assert merged["sentiment"]["sentiment"] == "positive"
    assert "ai" in merged["topics"]["topics"]
    assert merged["entities"]["entities"][0]["text"] == "Google"
    assert "42 words" in merged["summary"]


async def test_full_parallel_sectioning_flow(run_handler):
    """The flow-level function runs asyncio.gather internally — all stubs complete."""
    state = {"raw_text": "AI is transforming healthcare diagnostics globally."}
    result = await run_handler(parallel_sectioning(state))

    payload = result.payload
    assert "merged_result" in payload
    assert "sentiment" in payload["merged_result"]
    assert "topics" in payload["merged_result"]
    assert "entities" in payload["merged_result"]
    assert payload["word_count"] > 0


# ── parallel_sectioning: compiled fanout router ───────────────────────────────


async def test_fanout_router_emits_multiple_frames(run_handler, monkeypatch, load_routers):
    """The fanout router yields 1 parent frame + 3 slice frames = 4 frames total.

    This is the canonical fan-out scenario: result.payload would raise because
    there are 4 frames. result.frames is the correct API.
    """
    routers = load_routers("parallel_sectioning")
    monkeypatch.setattr(routers, "resolve", lambda name: f"actor-{name}")

    payload = {"text": "hello world", "other_field": "preserved"}
    result = await run_handler(
        routers.fanout_parallel_sectioning_line_44(payload),
        get_responses={
            ".id": "msg-001",
            ".route.next": ["actor-aggregator"],
        },
    )

    # result.payload would raise — there are 4 frames, not 1
    assert len(result.frames) == 4

    # Frame 0: parent payload forwarded to the fan-in aggregator
    parent_frame = result.frames[0]
    assert parent_frame["text"] == "hello world"
    assert parent_frame["other_field"] == "preserved"

    # Frames 1-3: one slice per specialist (text payload, not state dict)
    # Each slice is the raw "text" value passed to the specialist
    for slice_frame in result.frames[1:]:
        assert slice_frame == "hello world"


async def test_fanout_router_sets_fan_in_headers(run_handler, monkeypatch, load_routers):
    """Each yielded frame has x-asya-fan-in header with correct slice metadata."""
    routers = load_routers("parallel_sectioning")
    monkeypatch.setattr(routers, "resolve", lambda name: f"actor-{name}")

    result = await run_handler(
        routers.fanout_parallel_sectioning_line_44({"text": "test"}),
        get_responses={".id": "origin-42", ".route.next": []},
    )

    # Collect all SET commands for the fan-in header
    fan_in_sets = [e for e in result.abi if e[0] == "SET" and e[1] == ".headers.x-asya-fan-in"]
    assert len(fan_in_sets) == 4  # parent + 3 slices

    slice_indices = [e[2]["slice_index"] for e in fan_in_sets]
    assert sorted(slice_indices) == [0, 1, 2, 3]

    # All slices share the same origin_id and slice_count
    for cmd in fan_in_sets:
        meta = cmd[2]
        assert meta["origin_id"] == "origin-42"
        assert meta["slice_count"] == 4
        assert meta["aggregation_key"] == "/analysis"


async def test_fanout_router_routes_specialists_to_fan_in(run_handler, monkeypatch, load_routers):
    """Each slice actor routes to its specialist then to the fan-in aggregator."""
    routers = load_routers("parallel_sectioning")
    monkeypatch.setattr(routers, "resolve", lambda name: f"actor-{name}")

    result = await run_handler(
        routers.fanout_parallel_sectioning_line_44({"text": "data"}),
        get_responses={".id": "x", ".route.next": []},
    )

    route_sets = [e for e in result.abi if e[0] == "SET" and e[1] == ".route.next"]
    # Frame 0 (parent): routes to [fan-in, aggregator] + tail
    parent_route = route_sets[0][2]
    assert "actor-fanin_parallel_sectioning_line_44" in parent_route
    assert "actor-aggregator" in parent_route

    # Frames 1-3 (slices): each routes to [specialist, fan-in]
    for specialist_name, route_set in zip(
        ["sentiment_analyzer", "topic_extractor", "entity_recognizer"],
        route_sets[1:],
        strict=False,
    ):
        actors = route_set[2]
        assert f"actor-{specialist_name}" in actors
        assert "actor-fanin_parallel_sectioning_line_44" in actors


# ── map_reduce: handler stubs ─────────────────────────────────────────────────


async def test_splitter_divides_document_into_chunks(run_handler):
    doc = "a" * 90  # 90-char doc → 3 chunks of 30 chars each
    result = await run_handler(splitter({"document": doc}))

    payload = result.payload
    assert "chunks" in payload
    assert len(payload["chunks"]) == 3
    for i, chunk in enumerate(payload["chunks"]):
        assert chunk["index"] == i
        assert "content" in chunk


async def test_chunk_processor_summarises_chunk(run_handler):
    chunk = {"content": "This is the content of the chunk.", "index": 1}
    result = await run_handler(chunk_processor(chunk))

    payload = result.payload
    assert "summary" in payload
    assert "chunk 1" in payload["summary"]
    assert len(payload["key_points"]) == 3
    assert payload["word_count"] > 0


async def test_reducer_aggregates_chunk_results(run_handler):
    state = {
        "chunk_results": [
            {"summary": "S0", "key_points": ["p0a", "p0b"], "word_count": 10},
            {"summary": "S1", "key_points": ["p1a"], "word_count": 15},
            {"summary": "S2", "key_points": ["p2a", "p2b", "p2c"], "word_count": 8},
        ]
    }
    result = await run_handler(reducer(state))

    final = result.payload["final_result"]
    assert final["full_summary"] == "S0 S1 S2"
    assert len(final["all_key_points"]) == 6
    assert final["total_words"] == 33


async def test_full_map_reduce_flow(run_handler):
    state = {"document": "word " * 30}  # 30-word, 150-char document
    result = await run_handler(map_reduce(state))

    payload = result.payload
    assert "chunks" in payload
    assert "chunk_results" in payload
    assert "final_result" in payload
    assert len(payload["chunks"]) == 3
    assert len(payload["chunk_results"]) == 3
    assert payload["final_result"]["total_words"] > 0


# ── map_reduce: compiled fanout router ───────────────────────────────────────


async def test_map_reduce_fanout_emits_n_plus_one_frames(run_handler, monkeypatch, load_routers):
    """Fan-out yields 1 parent + N chunk frames where N = len(chunks).

    N is dynamic (determined at runtime by splitter), unlike parallel_sectioning
    which has a fixed 3 specialists.
    """
    routers = load_routers("map_reduce")
    monkeypatch.setattr(routers, "resolve", lambda name: f"actor-{name}")

    chunks = [{"content": f"chunk{i}", "index": i} for i in range(5)]
    payload = {"document": "...", "chunks": chunks}

    result = await run_handler(
        routers.fanout_map_reduce_line_49(payload),
        get_responses={".id": "msg-map-1", ".route.next": []},
    )

    # 1 parent + 5 chunks = 6 frames
    assert len(result.frames) == 6


async def test_map_reduce_fanout_fan_in_metadata(run_handler, monkeypatch, load_routers):
    """slice_count equals N+1, aggregation_key is /chunk_results."""
    routers = load_routers("map_reduce")
    monkeypatch.setattr(routers, "resolve", lambda name: f"actor-{name}")

    chunks = [{"content": f"c{i}", "index": i} for i in range(3)]
    result = await run_handler(
        routers.fanout_map_reduce_line_49({"chunks": chunks}),
        get_responses={".id": "map-orig", ".route.next": []},
    )

    fan_in_sets = [e for e in result.abi if e[0] == "SET" and e[1] == ".headers.x-asya-fan-in"]
    assert len(fan_in_sets) == 4  # 1 parent + 3 chunks

    for cmd in fan_in_sets:
        meta = cmd[2]
        assert meta["slice_count"] == 4
        assert meta["aggregation_key"] == "/chunk_results"
        assert meta["origin_id"] == "map-orig"
