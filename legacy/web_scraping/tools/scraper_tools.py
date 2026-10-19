"""Herramientas de Web Scraping profundo y extracción de metadatos estructurados de producto.

Soporta extracción de:
- Schema.org JSON-LD (`@type: Product`, `sku`, `mpn`, `gtin13`, `brand`, `offers`, `image`).
- Etiquetas OpenGraph (`og:title`, `og:description`, `og:image`, `product:retailer_item_id`).
- Tablas técnicas de especificaciones (`<table>`, `<dl>`) y texto limpio.
- Clasificación y validación automática del nivel de fuente (`official_only`, `trusted_pages`, `third_party_resellers`).
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from google.adk.tools.tool_context import ToolContext

from web_scraping.config import classify_url_source_tier


def _extract_json_ld_products(soup: BeautifulSoup) -> list[dict[str, Any]]:
    """Extrae objetos JSON-LD de tipo Product dentro del HTML."""
    products: list[dict[str, Any]] = []
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw.strip())
        except Exception:
            continue

        candidates = data if isinstance(data, list) else [data]
        for item in candidates:
            if not isinstance(item, dict):
                continue
            graph = item.get("@graph")
            if isinstance(graph, list):
                candidates.extend([g for g in graph if isinstance(g, dict)])
            item_type = str(item.get("@type", "")).lower()
            if "product" in item_type:
                products.append(item)
    return products


def _extract_spec_tables(soup: BeautifulSoup, max_pairs: int = 40) -> dict[str, str]:
    """Extrae pares clave-valor de tablas de especificaciones (`<table>` y `<dl>`)."""
    specs: dict[str, str] = {}

    for row in soup.find_all("tr"):
        cells = row.find_all(["th", "td"])
        if len(cells) == 2:
            key = " ".join(cells[0].get_text(" ", strip=True).split())
            val = " ".join(cells[1].get_text(" ", strip=True).split())
            if 1 < len(key) <= 60 and 1 <= len(val) <= 250:
                specs[key] = val
                if len(specs) >= max_pairs:
                    return specs

    for dl in soup.find_all("dl"):
        dts = dl.find_all("dt")
        dds = dl.find_all("dd")
        for dt, dd in zip(dts, dds):
            key = " ".join(dt.get_text(" ", strip=True).split())
            val = " ".join(dd.get_text(" ", strip=True).split())
            if 1 < len(key) <= 60 and 1 <= len(val) <= 250:
                specs[key] = val
                if len(specs) >= max_pairs:
                    return specs

    return specs


def scrape_product_webpage(
    url: str,
    expected_sku: str,
    expected_name: str,
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """Extrae metadatos estructurados, SKU, especificaciones e imágenes desde una URL de producto.

    Verifica automáticamente si la URL pertenece a las fuentes habilitadas en la configuración
    de la ejecución actual (`official_only`, `trusted_pages`, `third_party_resellers`).

    Args:
        url: URL completa de la página web a inspeccionar.
        expected_sku: SKU esperado del producto según el input inicial.
        expected_name: Nombre esperado del producto según el input inicial.
        tool_context: Contexto de herramientas de Google ADK.

    Returns:
        Diccionario con clasificación de fuente, coincidencia de SKU, datos JSON-LD,
        tabla de especificaciones e imágenes encontradas.
    """
    brand_domains: list[str] = []
    selected_sources: list[str] = [
        "official_only",
        "trusted_pages",
        "third_party_resellers",
    ]
    if tool_context is not None and "execution_plan" in tool_context.state:
        plan = tool_context.state["execution_plan"]
        brand_domains = plan["config"].get("brand_official_domains", [])
        selected_sources = plan["config"].get("selected_sources", selected_sources)

    tier = classify_url_source_tier(
        url=url,
        product_name=expected_name,
        brand_domains=brand_domains,
    )

    if tier.value not in selected_sources:
        return {
            "status": "FILTERED_BY_SOURCE_CONFIG",
            "url": url,
            "classified_tier": tier.value,
            "active_sources": selected_sources,
            "message": (
                f"La URL '{url}' fue clasificada como '{tier.value}', pero el usuario "
                f"solo habilitó las fuentes {selected_sources}. Fuente ignorada."
            ),
        }

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    }

    try:
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            resp = client.get(url, headers=headers)
            resp.raise_for_status()
            html_text = resp.text
    except Exception as exc:
        return {
            "status": "HTTP_ERROR",
            "url": url,
            "classified_tier": tier.value,
            "error": str(exc),
        }

    soup = BeautifulSoup(html_text, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else ""

    # Extraer OpenGraph
    og_data: dict[str, str] = {}
    for meta in soup.find_all("meta"):
        prop = str(meta.get("property") or meta.get("name") or "").lower()
        content = str(meta.get("content") or "").strip()
        if prop.startswith(("og:", "product:")) and content:
            og_data[prop] = content

    # Extraer JSON-LD Product
    json_ld_products = _extract_json_ld_products(soup)
    structured_product: dict[str, Any] = {}
    images_found: list[str] = []

    if og_data.get("og:image"):
        images_found.append(urljoin(url, og_data["og:image"]))

    for prod in json_ld_products:
        for field in ("name", "sku", "mpn", "gtin", "gtin13", "gtin12", "brand", "description", "offers"):
            if field in prod and field not in structured_product:
                structured_product[field] = prod[field]
        img = prod.get("image")
        if isinstance(img, str):
            images_found.append(urljoin(url, img))
        elif isinstance(img, list):
            for i in img[:5]:
                if isinstance(i, str):
                    images_found.append(urljoin(url, i))

    spec_table = _extract_spec_tables(soup)

    # Limpiar texto visible para verificación de SKU
    for tag in soup(["script", "style", "noscript", "svg", "footer", "nav"]):
        tag.decompose()
    visible_text = " ".join(soup.get_text(" ", strip=True).split())
    text_excerpt = visible_text[:3000]

    clean_sku = expected_sku.strip()
    sku_present_in_page = False
    if clean_sku:
        pattern = re.compile(re.escape(clean_sku), re.IGNORECASE)
        sku_present_in_page = bool(
            pattern.search(visible_text)
            or pattern.search(json.dumps(structured_product, ensure_ascii=False))
        )

    parsed_url = urlparse(url)
    result = {
        "status": "SUCCESS",
        "source_url": url,
        "source_domain": parsed_url.netloc.lower().removeprefix("www."),
        "source_tier": tier.value,
        "page_title": title,
        "sku_exact_match_in_page": sku_present_in_page,
        "json_ld_product": structured_product,
        "open_graph": og_data,
        "specification_table": spec_table,
        "image_urls_found": list(dict.fromkeys(images_found))[:5],
        "text_excerpt": text_excerpt,
    }

    if tool_context is not None:
        findings = list(tool_context.state.get("collected_findings", []))
        findings.append(result)
        tool_context.state["collected_findings"] = findings

    return result
