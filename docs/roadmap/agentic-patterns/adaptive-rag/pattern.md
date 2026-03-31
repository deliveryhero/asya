# Adaptive RAG with Iterative Retrieval

## Use-Case

Enterprise knowledge assistant that answers questions by searching across
multiple data sources (Confluence, Jira, Slack, codebase, internal wiki).
Evaluates relevance after each retrieval round and iterates if coverage
is insufficient — unlike simple RAG which retrieves once and generates.

## Why Asya

- **Fan-out to retrievers**: 5 retriever actors run in parallel via
  `asyncio.gather`, each specialized for one source with its own scaling,
  secrets, and rate limits.
- **Evaluator loop**: Critic actor scores combined results; if gaps detected,
  refines query and re-fans-out (`while` loop in Flow DSL).
- **State-in-message accumulates context**: Each retrieval round appends to
  `payload["retrieved_chunks"]`. The generator sees the full context across
  all iterations.
- **State-proxy for embedding cache**: Pre-computed embeddings stored in S3;
  retriever actors load once per pod lifecycle.
- **Independent secrets**: Each retriever actor has its own service account
  or API key — Confluence credentials never touch the Slack retriever pod.

## Architecture

```
Query Analyzer
      |
  [while coverage < 0.85, max 3 iterations]
      |
  +---+---+---+---+---+
  |   |   |   |   |   |  (fan-out)
  v   v   v   v   v   v
 Conf Jira Slack Code Wiki
  |   |   |   |   |   |
  +---+---+---+---+---+  (fan-in)
      |
  Relevance Evaluator
      |
  [if gaps: Query Refiner --> loop]
      |
  Generator (with full context)
      |
  Fact Checker
      |
  x-sink
```

## Example Flow

```python
@flow
async def adaptive_rag(p):
    p = await analyze_query(p)
    p["iteration"] = 0

    while p["iteration"] < 3:
        p["iteration"] += 1
        p["chunks"] = await asyncio.gather(
            confluence_retriever(p),
            jira_retriever(p),
            slack_retriever(p),
            code_retriever(p),
            wiki_retriever(p),
        )
        p = await relevance_evaluator(p)
        if p["coverage_score"] > 0.85:
            break
        p = await query_refiner(p)

    p = await generator(p)
    p = await fact_checker(p)
    return p
```
