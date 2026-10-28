"""Interactive Spanish console with persistent personal memory."""
from __future__ import annotations

import argparse
import asyncio
import json

from secop_agent.agent import SecopAssistant


async def chat(model: str | None = None, user_id: str = "default") -> None:
    """Read questions until salir, consolidating memory even on interruption."""
    print("SECOP · salir | /memoria | /olvida <texto>")
    async with SecopAssistant(model=model, user_id=user_id) as assistant:
        while True:
            try:
                question = (await asyncio.to_thread(input, "Tú> ")).strip()
            except EOFError:
                break
            if question.casefold() == "salir":
                break
            if question == "/memoria":
                print(json.dumps(await asyncio.to_thread(assistant.memory.snapshot), ensure_ascii=False, indent=2))
            elif question.startswith("/olvida "):
                count = await asyncio.to_thread(assistant.memory.forget, question[8:].strip())
                print(f"Hechos eliminados: {count}. Los resúmenes de sesiones se conservan.")
            elif question:
                result = await assistant.ask(question)
                print(result.answer)
                print("Citas:", "; ".join(result.citations) or "—")
                print(f"Coste: ${result.metrics['cost_usd']:.6f} USD · {result.metrics['latency_s']:.2f} s")
    print(f"Coste total de la sesión (incluye memoria): ${assistant.session_metrics['cost_usd']:.6f} USD")


def main() -> None:
    """Parse optional provider model and persistent user identity."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model")
    parser.add_argument("--user-id", default="default")
    args = parser.parse_args()
    try:
        asyncio.run(chat(args.model, args.user_id))
    except KeyboardInterrupt:
        print("\nSesión cerrada.")


if __name__ == "__main__":
    main()
