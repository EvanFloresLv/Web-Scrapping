"""Sub-agente Evaluador Crítico de Precisión (Triple Validación: Input + Oficial + Visual)."""

from __future__ import annotations

from google.adk.agents import Agent
from google.adk.tools.agent_tool import AgentTool

from web_scraping.config import get_pro_model
from web_scraping.prompts import PRECISION_EVALUATOR_AGENT_INSTRUCTION
from web_scraping.tools.config_tools import get_active_execution_plan
from web_scraping.tools.evaluation_tools import (
    evaluate_information_piece_confidence,
    verify_exact_product_identity,
)
from web_scraping.tools.vision_lens_tools import compare_product_images_visually

precision_evaluator_agent = Agent(
    name="precision_evaluator_engine",
    model=get_pro_model(),
    description=(
        "Agente evaluador crítico que audita el grado de confianza de cada pieza de información "
        "respecto al input inicial, a la página oficial del fabricante y al reconocimiento "
        "visual del producto (Google Lens / Gemini Multimodal), rechazando falsos positivos."
    ),
    instruction=PRECISION_EVALUATOR_AGENT_INSTRUCTION,
    tools=[
        get_active_execution_plan,
        verify_exact_product_identity,
        evaluate_information_piece_confidence,
        compare_product_images_visually,
    ],
)

precision_evaluator_engine_tool = AgentTool(agent=precision_evaluator_agent)
