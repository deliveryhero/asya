"""Text Improver: evaluator-optimizer content pipeline.

KubeCon demo flow. Compiles to distributed actor graph via `asya compile`.

Pipeline:
  research -> [while: generate -> evaluate -> break if score >= threshold] -> polish -> format_output

Configurable via payload:
  - topic (str): what to write about
  - threshold (int): quality score to accept (default 85)
  - max_iterations (int): max revision loops (default 3)
"""
from actors import research, generate, evaluate, polish, format_output


async def text_improver(p: dict) -> dict:  # asya: flow
    p["context"] = await research(p["topic"])
    p["feedback"] = ""

    p["iteration"] = 0
    while True:
        p["iteration"] += 1
        p["draft"] = await generate(p["topic"], p["context"], p["feedback"])
        p = evaluate(p)

        if p["score"] >= p.get("threshold", 85):
            break
        if p["iteration"] >= p.get("max_iterations", 3):
            break

    p["final"] = await polish(p["draft"])
    p["result"] = await format_output(p["final"], p["score"], p["iteration"])
    return p
