"""Text Improver: evaluator-optimizer content pipeline.

KubeCon demo flow. Compiles to distributed actor graph via `asya compile`.

Pipeline:
  research -> [while: generate -> evaluate -> break if score >= threshold] -> polish

Configurable via payload:
  - topic (str): what to write about
  - threshold (int): quality score to accept (default 85)
  - max_iterations (int): max revision loops (default 3)
"""
from actors import research, generate, evaluate, polish


async def text_improver(p: dict) -> dict:  # asya: flow
    p["topic"] = p.get("topic", p.get("query", "anything"))
    p["context"] = await research(p["topic"])

    while True:
        p["iteration"] = p.get("iteration", 1) + 1
        
        p["draft"] = await generate(p["topic"], p["context"])
        p = await evaluate(p)

        if p["score"] >= p.get("threshold", 85):
            break
        if p["iteration"] >= p.get("max_iterations", 3):
            break

    p["result"] = await polish(p["draft"])
    return p
