"""Text Improver: evaluator-optimizer content pipeline.

KubeCon demo flow. Compiles to distributed actor graph via `asya compile`.

Pipeline:
  research -> [while: generate -> evaluate -> break if score >= threshold]

Configurable via payload:
  - topic (str): what to write about
  - threshold (int): quality score to accept (default 80)
  - max_iterations (int): max revision loops (default 2)
"""

from actors import evaluate, generate, polish, research


async def text_improver(p: dict) -> dict:  # asya: flow
    p["context"] = await research(p["query"])

    p["iteration"] = 1
    while p["iteration"] <= p.get("max_iterations", 1):
        p["draft"] = await generate(p["query"], p["context"])

        p = await evaluate(p)
        if p["score"] >= p.get("threshold", 50):
            break

    p["result"] = await polish(p["draft"])

    return p
