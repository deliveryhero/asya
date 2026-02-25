def research_flow(p: dict) -> dict:
    p["results"] = [research_agent(t) for t in p["topics"]]
    p = summarizer(p)
    return p


def research_agent(payload: dict) -> dict:
    """Process a single research topic and return findings."""
    topic = payload.get("topic", payload) if isinstance(payload, dict) else payload
    return {
        "topic": topic,
        "findings": f"Research findings for: {topic}",
        "status": "researched",
    }


def summarizer(p: dict) -> dict:
    """Summarize all research results into a final report."""
    results = p.get("results", [])
    topics = [r.get("topic", "") for r in results if isinstance(r, dict)]
    p["summary"] = f"Summary of {len(results)} topics: {', '.join(topics)}"
    p["status"] = "completed"
    p["final"] = True
    return p
