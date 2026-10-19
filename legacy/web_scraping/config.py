"""Configuración modular para el agente ADK `web_scraping`.

Permite seleccionar de forma independiente o combinada en el input de cada ejecución:
1. Fuentes de información (`SourceTier`):
   - `official_only`: Solo páginas oficiales de la marca/fabricante.
   - `trusted_pages`: Páginas confiables (distribuidores autorizados, catálogos técnicos verificados).
   - `third_party_resellers`: Resellers y terceros (Amazon, Mercado Libre, eBay, marketplaces, etc.).
2. Motores de búsqueda (`SearchEngine`):
   - `google_search`: Búsqueda con Google Search Grounding nativo de Gemini.
   - `google_lens`: Reconocimiento visual tipo Google Lens con Gemini Multimodal.
   - `deep_research`: Investigación iterativa profunda y extracción de especificaciones web.
"""

from __future__ import annotations

import os
from enum import StrEnum
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator


class SourceTier(StrEnum):
    """Niveles de fuentes de información seleccionables por separado o juntas."""

    OFFICIAL_ONLY = "official_only"
    TRUSTED_PAGES = "trusted_pages"
    THIRD_PARTY_RESELLERS = "third_party_resellers"


class SearchEngine(StrEnum):
    """Motores de búsqueda e investigación seleccionables por separado o juntos."""

    GOOGLE_SEARCH = "google_search"
    GOOGLE_LENS = "google_lens"
    DEEP_RESEARCH = "deep_research"


# Alias amigables en español e inglés para facilitar el input en cada ejecución
SOURCE_TIER_ALIASES: dict[str, SourceTier] = {
    "official_only": SourceTier.OFFICIAL_ONLY,
    "official": SourceTier.OFFICIAL_ONLY,
    "oficial": SourceTier.OFFICIAL_ONLY,
    "pagina_oficial": SourceTier.OFFICIAL_ONLY,
    "solo_pagina_oficial": SourceTier.OFFICIAL_ONLY,
    "trusted_pages": SourceTier.TRUSTED_PAGES,
    "trusted": SourceTier.TRUSTED_PAGES,
    "confiables": SourceTier.TRUSTED_PAGES,
    "paginas_confiables": SourceTier.TRUSTED_PAGES,
    "third_party_resellers": SourceTier.THIRD_PARTY_RESELLERS,
    "third_party": SourceTier.THIRD_PARTY_RESELLERS,
    "3rd_party": SourceTier.THIRD_PARTY_RESELLERS,
    "eth_party": SourceTier.THIRD_PARTY_RESELLERS,
    "resellers": SourceTier.THIRD_PARTY_RESELLERS,
    "terceros": SourceTier.THIRD_PARTY_RESELLERS,
    "marketplaces": SourceTier.THIRD_PARTY_RESELLERS,
}

SEARCH_ENGINE_ALIASES: dict[str, SearchEngine] = {
    "google_search": SearchEngine.GOOGLE_SEARCH,
    "search": SearchEngine.GOOGLE_SEARCH,
    "google": SearchEngine.GOOGLE_SEARCH,
    "google_lens": SearchEngine.GOOGLE_LENS,
    "lens": SearchEngine.GOOGLE_LENS,
    "visual": SearchEngine.GOOGLE_LENS,
    "deep_research": SearchEngine.DEEP_RESEARCH,
    "deep": SearchEngine.DEEP_RESEARCH,
    "research": SearchEngine.DEEP_RESEARCH,
}

# Dominios conocidos de marketplaces / 3rd party resellers
KNOWN_THIRD_PARTY_DOMAINS: tuple[str, ...] = (
    "amazon.com",
    "amazon.com.mx",
    "amazon.es",
    "mercadolibre.com",
    "mercadolibre.com.mx",
    "mercadolibre.com.ar",
    "mercadolibre.com.co",
    "mercadolivre.com.br",
    "ebay.com",
    "aliexpress.com",
    "walmart.com",
    "walmart.com.mx",
    "linio.com",
    "coppel.com",
    "liverpool.com.mx",
    "falabella.com",
    "alkosto.com",
    "exito.com",
    "paris.cl",
    "ripley.cl",
    "newegg.com",
)

# Dominios conocidos de páginas confiables / catálogos técnicos / distribuidores autorizados
KNOWN_TRUSTED_DOMAINS: tuple[str, ...] = (
    "GS1.org",
    "icecat.biz",
    "openicecat.org",
    "bhphotovideo.com",
    "cdw.com",
    "digikey.com",
    "mouser.com",
    "ingrammicro.com",
    "techdata.com",
    "bestbuy.com",
    "pccomponentes.com",
    "cyberpuerta.mx",
    "elcorteingles.es",
    "mediamarkt.es",
    "rtings.com",
    "gsmarena.com",
    "notebookcheck.net",
)

# Pesos base de autoridad por tipo de fuente (0-100)
SOURCE_TIER_BASE_AUTHORITY: dict[SourceTier, float] = {
    SourceTier.OFFICIAL_ONLY: 95.0,
    SourceTier.TRUSTED_PAGES: 80.0,
    SourceTier.THIRD_PARTY_RESELLERS: 60.0,
}


def normalize_source_tiers(raw_sources: list[str] | str | None) -> list[SourceTier]:
    """Normaliza la lista de fuentes seleccionadas en el input de la ejecución."""
    if not raw_sources:
        return [
            SourceTier.OFFICIAL_ONLY,
            SourceTier.TRUSTED_PAGES,
            SourceTier.THIRD_PARTY_RESELLERS,
        ]
    if isinstance(raw_sources, str):
        items = [item.strip() for item in raw_sources.split(",") if item.strip()]
    else:
        items = [str(item).strip() for item in raw_sources if str(item).strip()]

    normalized: list[SourceTier] = []
    for item in items:
        key = item.lower().replace("-", "_").replace(" ", "_")
        if key in ("all", "todas", "todos", "*"):
            return [
                SourceTier.OFFICIAL_ONLY,
                SourceTier.TRUSTED_PAGES,
                SourceTier.THIRD_PARTY_RESELLERS,
            ]
        if key not in SOURCE_TIER_ALIASES:
            valid = ", ".join( [t.value for t in SourceTier] )
            raise ValueError(
                f"Fuente de información no reconocida: '{item}'. Opciones válidas: {valid}"
            )
        tier = SOURCE_TIER_ALIASES[key]
        if tier not in normalized:
            normalized.append(tier)
    return normalized


def normalize_search_engines(raw_engines: list[str] | str | None) -> list[SearchEngine]:
    """Normaliza la lista de motores de búsqueda seleccionados en el input de la ejecución."""
    if not raw_engines:
        return [
            SearchEngine.GOOGLE_SEARCH,
            SearchEngine.GOOGLE_LENS,
            SearchEngine.DEEP_RESEARCH,
        ]
    if isinstance(raw_engines, str):
        items = [item.strip() for item in raw_engines.split(",") if item.strip()]
    else:
        items = [str(item).strip() for item in raw_engines if str(item).strip()]

    normalized: list[SearchEngine] = []
    for item in items:
        key = item.lower().replace("-", "_").replace(" ", "_")
        if key in ("all", "todos", "todas", "*"):
            return [
                SearchEngine.GOOGLE_SEARCH,
                SearchEngine.GOOGLE_LENS,
                SearchEngine.DEEP_RESEARCH,
            ]
        if key not in SEARCH_ENGINE_ALIASES:
            valid = ", ".join([e.value for e in SearchEngine])
            raise ValueError(
                f"Motor de búsqueda no reconocido: '{item}'. Opciones válidas: {valid}"
            )
        engine = SEARCH_ENGINE_ALIASES[key]
        if engine not in normalized:
            normalized.append(engine)
    return normalized


class ExecutionConfig(BaseModel):
    """Configuración modular por ejecución pasada en el input del agente."""

    selected_sources: list[SourceTier] = Field(
        default_factory=lambda: [
            SourceTier.OFFICIAL_ONLY,
            SourceTier.TRUSTED_PAGES,
            SourceTier.THIRD_PARTY_RESELLERS,
        ],
        description=(
            "Fuentes activas para la búsqueda: 'official_only', 'trusted_pages', "
            "'third_party_resellers'. Se pueden elegir 1, 2 o las 3."
        ),
    )
    selected_engines: list[SearchEngine] = Field(
        default_factory=lambda: [
            SearchEngine.GOOGLE_SEARCH,
            SearchEngine.GOOGLE_LENS,
            SearchEngine.DEEP_RESEARCH,
        ],
        description=(
            "Motores de búsqueda activos: 'google_search', 'google_lens', "
            "'deep_research'. Se pueden elegir 1, 2 o los 3."
        ),
    )
    brand_official_domains: list[str] = Field(
        default_factory=list,
        description="Dominios oficiales conocidos o inferidos de la marca del producto (opcional).",
    )
    strict_sku_match: bool = Field(
        default=True,
        description="Exige validación estricta del SKU/modelo para evitar falsos positivos.",
    )
    minimum_precision_threshold: float = Field(
        default=75.0,
        ge=0.0,
        le=100.0,
        description="Umbral mínimo de confianza (0-100) para aceptar un atributo en el consolidado final.",
    )

    @field_validator("selected_sources", mode="before")
    @classmethod
    def _validate_sources(cls, v: Any) -> list[SourceTier]:
        return normalize_source_tiers(v)

    @field_validator("selected_engines", mode="before")
    @classmethod
    def _validate_engines(cls, v: Any) -> list[SearchEngine]:
        return normalize_search_engines(v)


def classify_url_source_tier(
    url: str,
    product_name: str = "",
    brand_domains: list[str] | None = None,
) -> SourceTier:
    """Clasifica una URL en uno de los 3 niveles de fuente (`SourceTier`)."""
    parsed = urlparse(url if "://" in url else f"https://{url}")
    host = (parsed.netloc or parsed.path).lower().removeprefix("www.")

    # 1. Verificar si pertenece a un dominio oficial explícito de la marca
    if brand_domains:
        for b_dom in brand_domains:
            clean_b = b_dom.lower().removeprefix("www.").strip()
            if clean_b and (host == clean_b or host.endswith(f".{clean_b}")):
                return SourceTier.OFFICIAL_ONLY

    # 2. Verificar si es un marketplace / 3rd party reseller conocido
    for tp_dom in KNOWN_THIRD_PARTY_DOMAINS:
        if host == tp_dom or host.endswith(f".{tp_dom}"):
            return SourceTier.THIRD_PARTY_RESELLERS

    # 3. Verificar si es una página confiable / distribuidor / catálogo técnico conocido
    for tr_dom in KNOWN_TRUSTED_DOMAINS:
        clean_tr = tr_dom.lower()
        if host == clean_tr or host.endswith(f".{clean_tr}"):
            return SourceTier.TRUSTED_PAGES

    # 4. Inferencia por marca en el nombre del producto
    tokens = [
        t.lower()
        for t in product_name.replace("-", " ").split()
        if len(t) >= 3 and t.isalnum()
    ]
    if tokens:
        brand_candidate = tokens[0]
        domain_root = host.split(".")[0]
        if brand_candidate == domain_root or brand_candidate in domain_root:
            return SourceTier.OFFICIAL_ONLY

    # Por defecto, sitios especializados o tiendas externas no oficiales se tratan como trusted o 3rd party
    return SourceTier.TRUSTED_PAGES


def build_source_search_directives(
    product_name: str,
    sku: str,
    selected_sources: list[SourceTier],
    brand_domains: list[str] | None = None,
) -> dict[str, Any]:
    """Construye consultas y reglas de filtrado específicas según las fuentes seleccionadas."""
    queries_by_tier: dict[str, list[str]] = {}
    base_term = f'"{sku}" "{product_name}"'.strip() if sku else f'"{product_name}"'

    if SourceTier.OFFICIAL_ONLY in selected_sources:
        if brand_domains:
            site_filter = " OR ".join([f"site:{d}" for d in brand_domains])
            queries_by_tier[SourceTier.OFFICIAL_ONLY.value] = [
                f"({site_filter}) {base_term}",
                f'({site_filter}) "{sku}" specifications datasheet',
            ]
        else:
            queries_by_tier[SourceTier.OFFICIAL_ONLY.value] = [
                f"{base_term} official site specifications",
                f'"{sku}" {product_name} fabricante pagina oficial ficha tecnica',
            ]

    if SourceTier.TRUSTED_PAGES in selected_sources:
        queries_by_tier[SourceTier.TRUSTED_PAGES.value] = [
            f'{base_term} ("datasheet" OR "ficha técnica" OR "especificaciones" OR "manual") -site:amazon.com -site:mercadolibre.com -site:ebay.com',
            f'"{sku}" "{product_name}" distribuidor autorizado catalogo tecnico',
        ]

    if SourceTier.THIRD_PARTY_RESELLERS in selected_sources:
        queries_by_tier[SourceTier.THIRD_PARTY_RESELLERS.value] = [
            f'{base_term} (site:amazon.com OR site:amazon.com.mx OR site:mercadolibre.com.mx OR site:mercadolibre.com OR site:ebay.com)',
            f'"{sku}" {product_name} reseller marketplace precio caracteristicas',
        ]

    return {
        "active_source_tiers": [s.value for s in selected_sources],
        "queries_by_tier": queries_by_tier,
        "allow_official": SourceTier.OFFICIAL_ONLY in selected_sources,
        "allow_trusted": SourceTier.TRUSTED_PAGES in selected_sources,
        "allow_third_party": SourceTier.THIRD_PARTY_RESELLERS in selected_sources,
    }


def get_default_model() -> str:
    """Devuelve el modelo Gemini configurado para los agentes."""
    return os.getenv("MODEL_NAME", "gemini-2.5-flash")


def get_pro_model() -> str:
    """Devuelve el modelo Gemini configurado para evaluación crítica y consolidación."""
    return os.getenv("PRO_MODEL_NAME", os.getenv("MODEL_NAME", "gemini-2.5-flash"))
