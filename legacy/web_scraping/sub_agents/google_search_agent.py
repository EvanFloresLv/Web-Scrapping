"""Sub-agente para el motor `google_search` con Google Search Grounding nativo de ADK."""

from __future__ import annotations

from google.adk.agents import Agent
from google.adk.tools import google_search
from google.adk.tools.agent_tool import AgentTool

from web_scraping.config import get_default_model
from web_scraping.prompts import GOOGLE_SEARCH_AGENT_INSTRUCTION

# En ADK, el agente que utiliza `google_search` nativo se mantiene dedicado a Grounding
# y se expone mediante `AgentTool` para coexistir limpiamente con FunctionTools.
google_search_agent = Agent(
    name="google_search_engine",
    model=get_default_model(),
    description=(
        "Motor de búsqueda web basado en Google Search Grounding nativo de Gemini. "
        "Busca información del producto (nombre, SKU, descripción) filtrando por las "
        "fuentes activas: official_only, trusted_pages y/o third_party_resellers."
    ),
    instruction=GOOGLE_SEARCH_AGENT_INSTRUCTION,
    tools=[google_search],
)

google_search_engine_tool = AgentTool(agent=google_search_agent)
