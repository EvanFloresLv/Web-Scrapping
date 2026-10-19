"""Sub-agente iterativo para el motor `deep_research` de investigación profunda y scraping web."""

from __future__ import annotations

from google.adk.agents import Agent
from google.adk.tools.agent_tool import AgentTool

from web_scraping.config import get_default_model
from web_scraping.prompts import DEEP_RESEARCH_AGENT_INSTRUCTION
from web_scraping.sub_agents.google_search_agent import google_search_engine_tool
from web_scraping.tools.config_tools import (
    check_url_allowed_by_config,
    get_active_execution_plan,
)
from web_scraping.tools.evaluation_tools import verify_exact_product_identity
from web_scraping.tools.scraper_tools import scrape_product_webpage

deep_research_agent = Agent(
    name="deep_research_engine",
    model=get_default_model(),
    description=(
        "Sub-agente iterativo de Deep Research que combina búsqueda multi-paso y scraping "
        "estructurado (JSON-LD, OpenGraph, tablas técnicas HTML) en páginas oficiales, "
        "confiables y/o resellers según la configuración activa."
    ),
    instruction=DEEP_RESEARCH_AGENT_INSTRUCTION,
    tools=[
        get_active_execution_plan,
        check_url_allowed_by_config,
        google_search_engine_tool,
        scrape_product_webpage,
        verify_exact_product_identity,
    ],
)

deep_research_engine_tool = AgentTool(agent=deep_research_agent)
