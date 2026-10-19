"""Esquemas de datos Pydantic para el flujo del agente `web_scraping`.

Define las estructuras de:
1. Input del producto + configuración de ejecución (`ProductScrapingInput`).
2. Hallazgos por motor y fuente (`SourceFinding`, `VisualLensAnalysis`).
3. Ranking de confiabilidad de fuentes (`SourceReliabilityRank`).
4. Crítica y evaluación de precisión por atributo (`AttributeCritique`, `EvaluationReport`).
5. Salida final consolidada (`ConsolidatedProductOutput`).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from web_scraping.config import ExecutionConfig, SearchEngine, SourceTier


class ConfidenceGrade(StrEnum):
    """Grado de confianza asignado por el Agente Evaluador a cada pieza de información."""

    CONFIRMED = "CONFIRMED"               # 90-100%: Coincide en Input + Oficial + Visual
    HIGH_CONFIDENCE = "HIGH_CONFIDENCE"   # 75-89%: Coincide con Input y fuente confiable/visual
    MEDIUM_CONFIDENCE = "MEDIUM_CONFIDENCE"  # 50-74%: Soportado parcialmente, sin contradicción
    LOW_CONFIDENCE = "LOW_CONFIDENCE"     # 25-49%: Fuente débil (ej. reseller aislado) o ambiguo
    REJECTED_MISMATCH = "REJECTED_MISMATCH"  # 0-24%: Contradice SKU, página oficial o imagen


class ProductScrapingInput(BaseModel):
    """Datos de entrada del producto y parámetros modulares por ejecución."""

    nombre: str = Field(..., description="Nombre comercial o modelo del producto buscado.")
    sku: str = Field(..., description="SKU, número de parte (MPN), UPC, EAN o GTIN del producto.")
    descripcion: str = Field(
        default="",
        description="Descripción inicial del producto para anclar la búsqueda y validación.",
    )
    imagen: str = Field(
        default="",
        description=(
            "URL de la imagen del producto, ruta local de archivo, data URI base64, "
            "o referencia a imagen adjunta en la conversación."
        ),
    )
    config: ExecutionConfig = Field(
        default_factory=ExecutionConfig,
        description="Configuración modular de fuentes y motores seleccionada para esta ejecución.",
    )


class VisualLensAnalysis(BaseModel):
    """Resultado del análisis visual tipo Google Lens con Gemini Multimodal."""

    image_provided: bool = Field(..., description="Indica si se proporcionó imagen de entrada.")
    image_source: str = Field(default="", description="URL o ruta de la imagen analizada.")
    detected_brand: str = Field(default="", description="Marca detectada visualmente (logo/texto).")
    detected_model_or_sku_text: list[str] = Field(
        default_factory=list,
        description="Textos, códigos de modelo o SKU leídos por OCR dentro de la imagen/empaque.",
    )
    visual_attributes: dict[str, str] = Field(
        default_factory=dict,
        description="Atributos físicos observados: color, forma, material, conectores, botones, etc.",
    )
    visual_fingerprints: list[str] = Field(
        default_factory=list,
        description="Rasgos visuales clave para distinguir este producto exacto de variantes o imitaciones.",
    )
    web_visual_matches: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Coincidencias visuales encontradas en la web y su grado de similitud morfológica.",
    )


class SourceFinding(BaseModel):
    """Hallazgo individual obtenido de una fuente web por uno de los motores."""

    source_url: str = Field(..., description="URL exacta de la página consultada.")
    source_domain: str = Field(..., description="Dominio de la página web.")
    source_title: str = Field(..., description="Título de la página o listado de producto.")
    source_tier: SourceTier = Field(
        ...,
        description="Nivel de la fuente: official_only, trusted_pages, o third_party_resellers.",
    )
    discovered_by_engine: SearchEngine = Field(
        ...,
        description="Motor que descubrió la información: google_search, google_lens, o deep_research.",
    )
    reported_product_name: str = Field(
        default="", description="Nombre del producto tal como aparece en la página."
    )
    reported_sku_or_mpn: str = Field(
        default="", description="SKU, MPN, ASIN o código reportado en la página."
    )
    sku_exact_match: bool = Field(
        default=False,
        description="True si el SKU/MPN reportado coincide exactamente con el SKU del input inicial.",
    )
    extracted_attributes: dict[str, Any] = Field(
        default_factory=dict,
        description="Atributos técnicos, dimensiones, precios, características e imágenes extraídas.",
    )
    image_urls_found: list[str] = Field(
        default_factory=list, description="URLs de imágenes del producto en esa página."
    )
    raw_excerpt: str = Field(
        default="", description="Extracto textual relevante de soporte/evidencia."
    )


class SourceReliabilityRank(BaseModel):
    """Entrada del ranking de confiabilidad generado por el Sub-Agente de Ranking."""

    rank_position: int = Field(..., ge=1, description="Posición en el ranking (1 = más confiable).")
    source_url: str = Field(..., description="URL de la fuente evaluada.")
    source_domain: str = Field(..., description="Dominio de la fuente.")
    source_tier: SourceTier = Field(..., description="Categoría de fuente.")
    discovered_by_engines: list[SearchEngine] = Field(
        default_factory=list, description="Motores que respaldan esta fuente."
    )
    reliability_score: float = Field(
        ..., ge=0.0, le=100.0, description="Puntaje de confiabilidad de la fuente (0 a 100)."
    )
    sku_match_score: float = Field(
        ..., ge=0.0, le=100.0, description="Puntaje de coincidencia exacta de SKU/modelo (0 a 100)."
    )
    domain_authority_score: float = Field(
        ..., ge=0.0, le=100.0, description="Puntaje por autoridad del dominio (Oficial > Confiable > 3rd Party)."
    )
    data_completeness_score: float = Field(
        ..., ge=0.0, le=100.0, description="Nivel de detalle técnico verificable en la página."
    )
    is_same_exact_product: bool = Field(
        ...,
        description="True únicamente si se confirma que la página describe exactamente el mismo producto buscado.",
    )
    ranking_justification: str = Field(
        ..., description="Explicación detallada de por qué recibió este puntaje y posición."
    )


class AttributeCritique(BaseModel):
    """Crítica del Agente Evaluador para cada pieza/atributo de información."""

    attribute_name: str = Field(..., description="Nombre del campo o especificación (ej. 'peso', 'voltaje', 'ean').")
    proposed_value: Any = Field(..., description="Valor extraído para el atributo.")
    supporting_sources: list[str] = Field(
        default_factory=list, description="URLs de las fuentes que reportan este valor."
    )
    alignment_with_initial_input: str = Field(
        ...,
        description="Evaluación frente al input inicial (nombre, SKU, descripción).",
    )
    alignment_with_official_page: str = Field(
        ...,
        description="Evaluación frente a la página oficial del fabricante (Ground Truth).",
    )
    alignment_with_visual_recognition: str = Field(
        ...,
        description="Evaluación frente al reconocimiento visual del producto (Google Lens / Gemini Vision).",
    )
    confidence_score: float = Field(
        ..., ge=0.0, le=100.0, description="Grado de confianza numérico (0 a 100)."
    )
    confidence_grade: ConfidenceGrade = Field(
        ..., description="Clasificación del grado de confianza."
    )
    accepted_for_consolidation: bool = Field(
        ...,
        description="True si supera el filtro de precisión y debe incluirse en el output final.",
    )
    evaluator_critique: str = Field(
        ..., description="Crítica detallada del agente evaluador sobre esta pieza de información."
    )


class RejectedSourceRecord(BaseModel):
    """Registro de fuentes o listados descartados por no corresponder al producto exacto."""

    source_url: str = Field(..., description="URL descartada.")
    rejection_reason: str = Field(
        ...,
        description="Motivo del descarte (ej. SKU de variante distinta, accesorio, discrepancia visual).",
    )


class ConsolidatedProductOutput(BaseModel):
    """Output único consolidado final producido tras el ranking y el agente evaluador."""

    input_product_summary: dict[str, Any] = Field(
        ..., description="Resumen del input inicial (nombre, sku, descripcion, imagen)."
    )
    execution_configuration: dict[str, Any] = Field(
        ...,
        description="Fuentes (`selected_sources`) y motores (`selected_engines`) utilizados en la ejecución.",
    )
    exact_product_match_verified: bool = Field(
        ...,
        description="Indicador crítico: True si la información consolidada corresponde con certeza al producto exacto buscado.",
    )
    overall_precision_score: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="Puntaje global de precisión sobre la identidad y datos del producto (0 a 100).",
    )
    consolidated_product_data: dict[str, Any] = Field(
        ...,
        description="Ficha técnica y comercial consolidada únicamente con los atributos validados.",
    )
    visual_verification_summary: dict[str, Any] = Field(
        default_factory=dict,
        description="Resumen del reconocimiento visual (Google Lens / Gemini Vision) frente al producto.",
    )
    source_reliability_ranking: list[SourceReliabilityRank] = Field(
        default_factory=list,
        description="Ranking ordenado de confiabilidad de cada fuente consultada.",
    )
    evaluator_critique_matrix: list[AttributeCritique] = Field(
        default_factory=list,
        description="Crítica individual de cada pieza de información respecto a input inicial, página oficial y reconocimiento visual.",
    )
    rejected_false_positives: list[RejectedSourceRecord] = Field(
        default_factory=list,
        description="Fuentes o datos descartados para proteger la máxima precisión del producto.",
    )
