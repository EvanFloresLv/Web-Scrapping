"""Sub-agente Consolidador Final de toda la información validada en un único output."""

from __future__ import annotations

from google.adk.agents import Agent
from google.adk.tools.agent_tool import AgentTool

from web_scraping.config import get_pro_model
from web_scraping.prompts import CONSOLIDATOR_AGENT_INSTRUCTION
from web_scraping.tools.config_tools import get_active_execution_plan

consolidator_agent = Agent(
    name="consolidator_engine",
    model=get_pro_model(),
    description=(
        "Sub-agente que consolida en un único output final estructurado todos los atributos "
        "que superaron el filtro del Agente Evaluador, junto con el Ranking de Confiabilidad "
        "de Fuentes y la Matriz de Crítica de Precisión."
    ),
    instruction=CONSOLIDATOR_AGENT_INSTRUCTION,
    tools=[get_active_execution_plan],
)

consolidator_engine_tool = AgentTool(agent=consolidator_agent)
