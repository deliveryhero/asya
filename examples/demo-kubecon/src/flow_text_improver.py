"""Text Improver: evaluator-optimizer content pipeline.

KubeCon demo flow. Compiles to distributed actor graph via `asya compile`.

Pipeline:
  research -> [while: generate -> evaluate -> break if score >= threshold]

Configurable via payload:
  - topic (str): what to write about
  - threshold (int): quality score to accept (default 80)
  - max_iterations (int): max revision loops (default 2)
"""
from actors import research, generate, evaluate


async def text_improver(p: dict) -> dict:  # asya: flow
    p["topic"] = p.get("topic", p.get("query", "anything"))
    p["context"] = await research(p["topic"])

    while True:
        p["iteration"] = p.get("iteration", 0) + 1
        p["draft"] = await generate(p["topic"], p["context"])
        p = await evaluate(p)

        if p["score"] >= p.get("threshold", 60):
            break
        if p["iteration"] >= p.get("max_iterations", 2):
            break

    return p
