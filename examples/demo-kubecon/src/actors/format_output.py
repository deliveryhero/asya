"""Formatter actor: structure the final output."""


async def format_output(draft: str, score: int, iterations: int) -> dict:  # asya: actor
    result = {
        "text": draft,
        "quality_score": score,
        "iterations_used": iterations,
        "status": "approved" if score >= 85 else "best_effort",
    }
    print(f"[+] formatted output (score={score}, iterations={iterations})")
    return result
