"""Sub-agente para el motor `google_lens` 100% basado en Gemini Multimodal."""

from __future__ import annotations

from google.adk.agents import Agent
from google.adk.tools.agent_tool import AgentTool

from web_scraping.config import get_default_model
from web_scraping.prompts import GOOGLE_LENS_AGENT_INSTRUCTION
from web_scraping.sub_agents.google_search_agent import google_search_engine_tool
from web_scraping.tools.vision_lens_tools import (
    analyze_product_image_lens,
    compare_product_images_visually,
    register_visual_lens_profile,
)

google_lens_agent = Agent(
    name="google_lens_engine",
    model=get_default_model(),
    description=(
        "Motor de reconocimiento y búsqueda visual tipo Google Lens basado en Gemini Multimodal. "
        "Analiza la imagen del producto (OCR de SKU/modelo en empaque, marca, color, puertos, "
        "huella visual) y compara visualmente las fotos de páginas web candidatas."
    ),
    instruction=GOOGLE_LENS_AGENT_INSTRUCTION,
    tools=[
        analyze_product_image_lens,
        register_visual_lens_profile,
        compare_product_images_visually,
        google_search_engine_tool,
    ],
)

google_lens_engine_tool = AgentTool(agent=google_lens_agent)
