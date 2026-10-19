"""Exportación de sub-agentes y AgentTools del sistema `web_scraping`."""

from web_scraping.sub_agents.consolidator_agent import (
    consolidator_agent,
    consolidator_engine_tool,
)
from web_scraping.sub_agents.deep_research_agent import (
    deep_research_agent,
    deep_research_engine_tool,
)
from web_scraping.sub_agents.google_lens_agent import (
    google_lens_agent,
    google_lens_engine_tool,
)
from web_scraping.sub_agents.google_search_agent import (
    google_search_agent,
    google_search_engine_tool,
)
from web_scraping.sub_agents.precision_evaluator_agent import (
    precision_evaluator_agent,
    precision_evaluator_engine_tool,
)
from web_scraping.sub_agents.reliability_ranking_agent import (
    reliability_ranking_agent,
    reliability_ranking_engine_tool,
)

__all__ = [
    "google_search_agent",
    "google_search_engine_tool",
    "google_lens_agent",
    "google_lens_engine_tool",
    "deep_research_agent",
    "deep_research_engine_tool",
    "reliability_ranking_agent",
    "reliability_ranking_engine_tool",
    "precision_evaluator_agent",
    "precision_evaluator_engine_tool",
    "consolidator_agent",
    "consolidator_engine_tool",
]
