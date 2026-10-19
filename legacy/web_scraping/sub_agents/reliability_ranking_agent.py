"""Sub-agente analizador de salidas y generador del Ranking de Confiabilidad de Fuentes."""

from __future__ import annotations

from google.adk.agents import Agent
from google.adk.tools.agent_tool import AgentTool

from web_scraping.config import get_default_model
from web_scraping.prompts import RELIABILITY_RANKING_AGENT_INSTRUCTION
from web_scraping.tools.config_tools import (
    check_url_allowed_by_config,
    get_active_execution_plan,
)
from web_scraping.tools.evaluation_tools import (
    compute_source_reliability_ranking,
    verify_exact_product_identity,
)

reliability_ranking_agent = Agent(
    name="reliability_ranking_engine",
    model=get_default_model(),
    description=(
        "Sub-agente que analiza todas las salidas de los motores de búsqueda activos, "
        "filtra por las fuentes seleccionadas y genera un ranking ordenado de confiabilidad "
        "de cada fuente con base en autoridad de dominio y coincidencia exacta de SKU."
    ),
    instruction=RELIABILITY_RANKING_AGENT_INSTRUCTION,
    tools=[
        get_active_execution_plan,
        check_url_allowed_by_config,
        verify_exact_product_identity,
        compute_source_reliability_ranking,
    ],
)

reliability_ranking_engine_tool = AgentTool(agent=reliability_ranking_agent)
