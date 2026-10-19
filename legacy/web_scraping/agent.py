"""Definición del agente raíz ADK `web_scraping` (`root_agent`).

Orquesta de manera modular:
1. Configuración por ejecución de:
   - Fuentes (`official_only`, `trusted_pages`, `third_party_resellers` - individuales o combinadas)
   - Motores (`google_search`, `google_lens`, `deep_research` - individuales o combinados)
2. Ejecución de los motores seleccionados con prioridad absoluta en la precisión del SKU/producto.
3. Análisis y Ranking de Confiabilidad de cada fuente (`reliability_ranking_engine`).
4. Crítica y Evaluación de Confianza de cada pieza de información respecto al Input Inicial,
   Página Oficial y Reconocimiento Visual (`precision_evaluator_engine`).
5. Consolidación en un único output estructurado (`consolidator_engine`).
"""

from __future__ import annotations

from dotenv import load_dotenv
from google.adk.agents import Agent

from web_scraping.config import get_pro_model
from web_scraping.prompts import ROOT_ORCHESTRATOR_INSTRUCTION
from web_scraping.sub_agents import (
    consolidator_engine_tool,
    deep_research_engine_tool,
    google_lens_engine_tool,
    google_search_engine_tool,
    precision_evaluator_engine_tool,
    reliability_ranking_engine_tool,
)
from web_scraping.tools import (
    check_url_allowed_by_config,
    configure_scraping_execution,
    get_active_execution_plan,
)

load_dotenv()

web_scraping = Agent(
    name="web_scraping",
    model=get_pro_model(),
    description=(
        "Agente modular de Web Scraping e Inteligencia de Productos. Recibe nombre, SKU, "
        "descripción, imagen y selección dinámica de fuentes (official_only, trusted_pages, "
        "third_party_resellers) y motores (google_search, google_lens, deep_research). "
        "Genera ranking de confiabilidad, evaluación crítica triple y output consolidado."
    ),
    instruction=ROOT_ORCHESTRATOR_INSTRUCTION,
    tools=[
        configure_scraping_execution,
        get_active_execution_plan,
        check_url_allowed_by_config,
        google_search_engine_tool,
        google_lens_engine_tool,
        deep_research_engine_tool,
        reliability_ranking_engine_tool,
        precision_evaluator_engine_tool,
        consolidator_engine_tool,
    ],
)

# `root_agent` es el entrypoint estándar requerido por `adk web` y `adk run`
root_agent = web_scraping
