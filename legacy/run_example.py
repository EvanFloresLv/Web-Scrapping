"""Script de ejemplo para invocar el agente ADK `web_scraping` programáticamente."""

from __future__ import annotations

import asyncio
import json

from google.adk.runners import InMemoryRunner
from google.genai import types

from web_scraping.agent import root_agent


async def run_sample_query() -> None:
    """Ejecuta una consulta de ejemplo pasando la configuración modular en el input."""
    sample_payload = {
        "nombre": "Sony WH-1000XM5",
        "sku": "WH1000XM5/B",
        "descripcion": (
            "Audífonos inalámbricos noise cancelling de diadema, color negro, "
            "procesador V1 + QN1, hasta 30 horas de batería, carga USB-C."
        ),
        "imagen": "https://www.sony.com/image/5d02da5df552836db894cead8a68f5f3?fmt=png-alpha",
        "fuentes": [
            "official_only",
            "trusted_pages",
            "third_party_resellers",
        ],
        "motores": [
            "google_search",
            "google_lens",
            "deep_research",
        ],
        "dominios_oficiales": ["sony.com", "sony.com.mx", "sony.es"],
    }

    runner = InMemoryRunner(agent=root_agent, app_name="web_scraping_app")
    session = await runner.session_service.create_session(
        app_name="web_scraping_app",
        user_id="demo_user",
    )

    user_message = types.Content(
        role="user",
        parts=[
            types.Part.from_text(
                text=(
                    "Investiga, evalúa y consolida la información del siguiente producto "
                    "usando la configuración modular indicada:\n"
                    f"```json\n{json.dumps(sample_payload, indent=2, ensure_ascii=False)}\n```"
                )
            )
        ],
    )

    print("=== Iniciando ejecución del agente ADK `web_scraping` ===")
    async for event in runner.run_async(
        user_id="demo_user",
        session_id=session.id,
        new_message=user_message,
    ):
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    print(f"\n[{event.author}]:\n{part.text}")


if __name__ == "__main__":
    asyncio.run(run_sample_query())
