"""Herramientas de configuración modular por ejecución para el agente `web_scraping`."""

from __future__ import annotations

from typing import Any

from google.adk.tools.tool_context import ToolContext

from web_scraping.config import (
    ExecutionConfig,
     build_source_search_directives,
    classify_url_source_tier,
)
from web_scraping.schemas import ProductScrapingInput


def configure_scraping_execution(
    nombre: str,
    sku: str,
    descripcion: str = "",
    imagen: str = "",
    fuentes: list[str] | str | None = None,
    motores: list[str] | str | None = None,
    dominios_oficiales: list[str] | None = None,
    umbral_precision: float = 75.0,
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """Configura y valida los parámetros del producto, fuentes y motores para la ejecución actual.

    Args:
        nombre: Nombre comercial o modelo del producto a buscar.
        sku: SKU exacto, número de parte (MPN), EAN, UPC o GTIN del producto.
        descripcion: Descripción inicial del producto proporcionada por el usuario.
        imagen: URL, ruta local o referencia a la imagen del producto.
        fuentes: Fuentes habilitadas para esta ejecución. Opciones combinables:
            - 'official_only' (o 'pagina_oficial')
            - 'trusted_pages' (o 'paginas_confiables')
            - 'third_party_resellers' (o 'eth_party', 'resellers', 'terceros')
            Si no se especifica, habilita las 3.
        motores: Motores de búsqueda habilitados para esta ejecución. Opciones combinables:
            - 'google_search'
            - 'google_lens'
            - 'deep_research'
            Si no se especifica, habilita los 3.
        dominios_oficiales: Lista opcional de dominios oficiales de la marca (ej. ['sony.com']).
        umbral_precision: Puntaje mínimo de confianza (0-100) para aceptar datos en el output final.
        tool_context: Contexto de sesión de Google ADK.

    Returns:
        Diccionario con el plan de ejecución validado, fuentes activas, motores activos
        y directivas de búsqueda para cada sub-agente.
    """
    exec_config = ExecutionConfig(
        selected_sources=fuentes,  # type: ignore[arg-type]
        selected_engines=motores,  # type: ignore[arg-type]
        brand_official_domains=dominios_oficiales or [],
        strict_sku_match=True,
        minimum_precision_threshold=umbral_precision,
    )

    product_input = ProductScrapingInput(
        nombre=nombre.strip(),
        sku=sku.strip(),
        descripcion=descripcion.strip(),
        imagen=imagen.strip(),
        config=exec_config,
    )

    directives = build_source_search_directives(
        product_name=product_input.nombre,
        sku=product_input.sku,
        selected_sources=exec_config.selected_sources,
        brand_domains=exec_config.brand_official_domains,
    )

    execution_plan = {
        "product_input": {
            "nombre": product_input.nombre,
            "sku": product_input.sku,
            "descripcion": product_input.descripcion,
            "imagen": product_input.imagen,
        },
        "config": {
            "selected_sources": [s.value for s in exec_config.selected_sources],
            "selected_engines": [e.value for e in exec_config.selected_engines],
            "brand_official_domains": exec_config.brand_official_domains,
            "strict_sku_match": exec_config.strict_sku_match,
            "minimum_precision_threshold": exec_config.minimum_precision_threshold,
        },
        "search_directives": directives,
        "engines_to_invoke": {
            "run_google_search": "google_search" in [e.value for e in exec_config.selected_engines],
            "run_google_lens": "google_lens" in [e.value for e in exec_config.selected_engines],
            "run_deep_research": "deep_research" in [e.value for e in exec_config.selected_engines],
        },
    }

    if tool_context is not None:
        tool_context.state["execution_plan"] = execution_plan
        tool_context.state["collected_findings"] = []
        tool_context.state["visual_analysis"] = {}

    return {
        "status": "CONFIGURED",
        "message": (
            f"Ejecución configurada para SKU '{product_input.sku}' ({product_input.nombre}). "
            f"Fuentes activas: {[s.value for s in exec_config.selected_sources]}. "
            f"Motores activos: {[e.value for e in exec_config.selected_engines]}."
        ),
        "execution_plan": execution_plan,
    }


def get_active_execution_plan(tool_context: ToolContext | None = None) -> dict[str, Any]:
    """Obtiene el plan de ejecución activo desde el estado de la sesión de ADK."""
    if tool_context is not None and "execution_plan" in tool_context.state:
        return {
            "status": "FOUND",
            "execution_plan": tool_context.state["execution_plan"],
        }
    return {
        "status": "NOT_CONFIGURED",
        "message": (
            "Aún no se ha llamado a `configure_scraping_execution`. "
            "Ejecútala primero con los parámetros del input del usuario."
        ),
    }


def check_url_allowed_by_config(
    url: str,
    product_name: str = "",
    selected_sources: list[str] | None = None,
    brand_domains: list[str] | None = None,
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """Clasifica una URL y verifica si pertenece a las fuentes permitidas en esta ejecución."""
    if tool_context is not None and "execution_plan" in tool_context.state:
        plan = tool_context.state["execution_plan"]
        if not product_name:
            product_name = plan["product_input"].get("nombre", "")
        if selected_sources is None:
            selected_sources = plan["config"].get("selected_sources", [])
        if brand_domains is None:
            brand_domains = plan["config"].get("brand_official_domains", [])

    tier = classify_url_source_tier(
        url=url,
        product_name=product_name,
        brand_domains=brand_domains,
    )
    allowed_list = selected_sources or [
        "official_only",
        "trusted_pages",
        "third_party_resellers",
    ]
    is_allowed = tier.value in allowed_list

    return {
        "url": url,
        "classified_tier": tier.value,
        "allowed_in_current_execution": is_allowed,
        "active_sources": allowed_list,
    }
