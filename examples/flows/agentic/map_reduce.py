"""
Map-Reduce - same operation applied to data partitions, results aggregated.

A splitter divides a large input into chunks. The SAME processing operation
is applied to each chunk independently (map phase). A reducer aggregates
all chunk results into a final output (reduce phase).

Unlike Parallel Sectioning (different tasks on same data), Map-Reduce
applies the SAME task to DIFFERENT data slices.

Pattern: splitter -> fan-out [process_chunk x N] -> reducer

Framework references:
  - LangGraph Map-Reduce tutorial
    https://langchain-ai.github.io/langgraph/how-tos/map-reduce/
  - General distributed systems: MapReduce (Dean & Ghemawat, 2004)
  - LlamaIndex: document summarization via map-reduce
    https://docs.llamaindex.ai/en/stable/

Use cases:
  - Summarize a long document (split into sections, summarize each, combine)
  - Extract entities from a large dataset (process each record independently)
  - Translate a book (translate each chapter independently, merge)
  - Grade multiple student submissions (same rubric, different papers)

Deployment:
  - splitter: divides input into chunks
  - chunk_processor: applied identically to each chunk (same actor, N instances)
  - reducer: aggregates all chunk results

Payload contract:
  state["document"]       - the large input to process
  state["chunks"]         - list of data partitions (set by splitter)
  state["chunk_results"]  - list of processed chunks (set by fan-out)
  state["final_result"]   - aggregated output (set by reducer)

The list comprehension syntax enables dynamic fan-out -- the number of
chunks is determined at runtime by the splitter actor. The compiler
generates a fan-out router that dispatches N messages (one per chunk)
and a fan-in aggregator that collects all results.
"""


async def map_reduce(state: dict) -> dict:
    import asyncio

    # Split: divide large input into manageable chunks
    state = await splitter(state)

    # Map: apply same operation to each chunk (dynamic fan-out)
    state["chunk_results"] = list(
        await asyncio.gather(*[chunk_processor(chunk) for chunk in state["chunks"]])
    )

    # Reduce: aggregate all chunk results into final output
    state = await reducer(state)
    return state


# --- Handler stubs ---


async def splitter(state: dict) -> dict:
    """Actor: divide input into chunks for parallel processing.

    Splits state["document"] into state["chunks"]. Splitting strategy
    depends on the use case:
    - Text: by paragraph, section, or token count
    - Data: by record count or partition key
    - Code: by file or function
    """
    document = state["document"]
    chunks = [
        {
            "content": document[:len(document)//3],
            "index": 0
        },
        {
            "content": document[len(document)//3:2*len(document)//3],
            "index": 1
        },
        {
            "content": document[2*len(document)//3:],
            "index": 2
        }
    ]
    state["chunks"] = chunks
    return state


async def chunk_processor(chunk: dict) -> dict:
    """LLM actor: process a single chunk (the "map" operation).

    The same actor handles all chunks -- KEDA scales it based on
    queue depth. Each instance processes one chunk independently.

    Example operations:
    - Summarize a text section
    - Extract entities from a data partition
    - Translate a chapter
    """
    content = chunk["content"]
    word_count = len(content.split())

    return {
        "summary": f"Summary of chunk {chunk['index']}: {content[:50]}...",
        "key_points": [
            f"Point 1 from chunk {chunk['index']}",
            f"Point 2 from chunk {chunk['index']}",
            f"Point 3 from chunk {chunk['index']}"
        ],
        "word_count": word_count
    }


async def reducer(state: dict) -> dict:
    """Actor: aggregate chunk results into final output.

    Reads state["chunk_results"] and combines them into
    state["final_result"]. Aggregation strategy varies:
    - Concatenation with transitions (summaries)
    - Deduplication and merging (entity extraction)
    - Majority voting (classification)
    """
    chunk_results = state["chunk_results"]

    all_summaries = [r["summary"] for r in chunk_results]
    all_key_points = []
    for r in chunk_results:
        all_key_points.extend(r["key_points"])
    total_words = sum(r["word_count"] for r in chunk_results)

    state["final_result"] = {
        "full_summary": " ".join(all_summaries),
        "all_key_points": all_key_points,
        "total_words": total_words
    }
    return state
