"""Herramientas de reconocimiento visual tipo Google Lens 100% basadas en Gemini Multimodal.

Permite:
1. Analizar la imagen de entrada del producto (URL, ruta local, base64 o imagen adjunta en ADK)
   para extraer OCR de etiquetas/SKU, marca, modelo, puertos, color, empaque y huella visual.
2. Comparar visualmente imágenes encontradas en páginas web (oficiales, confiables o resellers)
   contra la imagen de referencia para garantizar que correspondan exactamente al mismo producto.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import httpx
from google import genai
from google.adk.tools.tool_context import ToolContext
from google.genai import types

from web_scraping.config import get_default_model


def _load_image_bytes(image_source: str) -> tuple[bytes, str]:
    """Carga bytes y mime_type de una imagen desde URL, ruta local o data URI base64."""
    src = image_source.strip()
    if src.startswith("data:image/"):
        header, b64_data = src.split(",", 1)
        mime_type = header.split(";")[0].replace("data:", "")
        return base64.b64decode(b64_data), mime_type

    if src.startswith(("http://", "https://")):
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            resp = client.get(
                src,
                headers={"User-Agent": "Mozilla/5.0 (compatible; ADKWebScrapingBot/1.0)"},
            )
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
            if not content_type.startswith("image/"):
                content_type = "image/jpeg"
            return resp.content, content_type

    path = Path(src).expanduser()
    if path.is_file():
        suffix = path.suffix.lower()
        mime_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".gif": "image/gif",
        }
        return path.read_bytes(), mime_map.get(suffix, "image/jpeg")

    raise ValueError(f"No se pudo cargar la imagen desde '{image_source}'.")


def analyze_product_image_lens(
    image_source: str,
    expected_name: str,
    expected_sku: str,
    expected_description: str = "",
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """Analiza una imagen de producto con Gemini Multimodal (modo Google Lens).

    Extrae marca, textos impresos (OCR de SKU, número de parte, códigos de barras),
    atributos físicos (color, forma, puertos, botones, material) y genera consultas
    de búsqueda visual para encontrar exactamente el mismo producto en la web.

    Args:
        image_source: URL HTTP(S), ruta de archivo local o data URI base64 de la imagen.
        expected_name: Nombre esperado del producto según el input inicial.
        expected_sku: SKU esperado según el input inicial.
        expected_description: Descripción inicial del producto.
        tool_context: Contexto de herramientas de ADK.

    Returns:
        Diccionario con el análisis visual estructurado y nivel de coincidencia con el input.
    """
    if not image_source or not image_source.strip():
        return {
            "status": "NO_IMAGE_SOURCE_STRING",
            "message": (
                "No se proporcionó URL/ruta de imagen en texto. Si el usuario adjuntó una imagen "
                "directamente en el chat, analízala con tu capacidad multimodal nativa y regístrala "
                "con `register_visual_lens_profile`."
            ),
        }

    try:
        img_bytes, mime_type = _load_image_bytes(image_source)
    except Exception as exc:
        return {
            "status": "IMAGE_LOAD_ERROR",
            "image_source": image_source,
            "error": str(exc),
            "message": (
                "No fue posible descargar o leer la imagen directamente. "
                "Usa los atributos descriptivos y el SKU para validar las imágenes web."
            ),
        }

    prompt = f"""Eres un sistema experto de reconocimiento visual de productos tipo Google Lens.
Analiza con máxima precisión la imagen adjunta y compárala con el input inicial:
- Nombre esperado: {expected_name}
- SKU esperado: {expected_sku}
- Descripción inicial: {expected_description}

Devuelve EXCLUSIVAMENTE un objeto JSON válido con la siguiente estructura:
{{
  "detected_brand": "Marca visible en logo o empaque",
  "detected_model_or_sku_text": ["todos los textos, modelos, SKUs, MPN o códigos impresos visibles por OCR"],
  "visual_attributes": {{
    "color_primary": "...",
    "form_factor": "...",
    "materials": "...",
    "ports_or_connectors": "...",
    "buttons_or_controls": "...",
    "packaging_details": "..."
  }},
  "visual_fingerprints": [
    "3 a 5 rasgos visuales únicos que permiten distinguir este modelo exacto de otras versiones o imitaciones"
  ],
  "matches_initial_input": true,
  "input_alignment_explanation": "Explicación de si la imagen corresponde al nombre, SKU y descripción del input",
  "suggested_visual_search_queries": [
    "consulta exacta 1 para encontrar este producto idéntico",
    "consulta exacta 2 incluyendo rasgos visuales y SKU"
  ]
}}"""

    try:
        client = genai.Client()
        response = client.models.generate_content(
            model=get_default_model(),
            contents=[
                types.Part.from_bytes(data=img_bytes, mime_type=mime_type),
                prompt,
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1,
            ),
        )
        parsed = json.loads(response.text or "{}")
    except Exception as exc:
        return {
            "status": "GEMINI_VISION_ERROR",
            "image_source": image_source,
            "error": str(exc),
        }

    result = {
        "status": "SUCCESS",
        "image_provided": True,
        "image_source": image_source,
        **parsed,
    }

    if tool_context is not None:
        tool_context.state["visual_analysis"] = result

    return result


def register_visual_lens_profile(
    detected_brand: str,
    detected_model_or_sku_text: list[str],
    visual_attributes: dict[str, str],
    visual_fingerprints: list[str],
    matches_initial_input: bool,
    input_alignment_explanation: str,
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """Registra en el estado de la sesión el perfil visual extraído por el agente Google Lens.

    Útil tanto cuando la imagen fue adjuntada directamente como contenido multimodal en el chat
    de ADK como después de inspeccionar imágenes encontradas en las fuentes web.
    """
    profile = {
        "status": "SUCCESS",
        "image_provided": True,
        "detected_brand": detected_brand,
        "detected_model_or_sku_text": detected_model_or_sku_text,
        "visual_attributes": visual_attributes,
        "visual_fingerprints": visual_fingerprints,
        "matches_initial_input": matches_initial_input,
        "input_alignment_explanation": input_alignment_explanation,
    }
    if tool_context is not None:
        tool_context.state["visual_analysis"] = profile
    return profile


def compare_product_images_visually(
    reference_image_source: str,
    candidate_image_url: str,
    expected_sku: str,
    expected_name: str,
) -> dict[str, Any]:
    """Compara visualmente la imagen original del input con la imagen de una página web encontrada.

    Determina si ambas imágenes muestran exactamente el mismo producto y variante de SKU,
    detectando diferencias de generación, color, conectores o si es un accesorio distinto.
    """
    try:
        ref_bytes, ref_mime = _load_image_bytes(reference_image_source)
        cand_bytes, cand_mime = _load_image_bytes(candidate_image_url)
    except Exception as exc:
        return {
            "status": "COMPARISON_SKIPPED",
            "reason": f"No se pudieron descargar ambas imágenes para comparación directa: {exc}",
            "candidate_image_url": candidate_image_url,
        }

    prompt = f"""Compara estas dos imágenes de producto:
- Imagen 1: Imagen de referencia del input inicial para '{expected_name}' (SKU: {expected_sku}).
- Imagen 2: Imagen candidata encontrada en una página web ({candidate_image_url}).

Evalúa con rigor extremo si la Imagen 2 muestra EXACTAMENTE el mismo modelo y variante física que la Imagen 1.
Presta atención a: forma, disposición de puertos/botones, proporciones, color, tipografía del logo y versión.

Responde EXCLUSIVAMENTE en JSON con este formato:
{{
  "is_exact_visual_match": true,
  "visual_similarity_score": 95.0,
  "matching_features": ["rasgo coincidente 1", "rasgo coincidente 2"],
  "discrepancies_found": ["diferencia detectada si existe"],
  "verdict_explanation": "Explicación técnica del veredicto visual"
}}"""

    try:
        client = genai.Client()
        response = client.models.generate_content(
            model=get_default_model(),
            contents=[
                types.Part.from_bytes(data=ref_bytes, mime_type=ref_mime),
                types.Part.from_bytes(data=cand_bytes, mime_type=cand_mime),
                prompt,
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1,
            ),
        )
        return {
            "status": "SUCCESS",
            "reference_image": reference_image_source,
            "candidate_image_url": candidate_image_url,
            **json.loads(response.text or "{}"),
        }
    except Exception as exc:
        return {
            "status": "COMPARISON_ERROR",
            "candidate_image_url": candidate_image_url,
            "error": str(exc),
        }
