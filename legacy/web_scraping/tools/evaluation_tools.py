"""Herramientas de Ranking de Confiabilidad y Evaluación Crítica de Precisión (Triple Validación).

La prioridad máxima de este módulo es garantizar que toda la información aceptada corresponda
EXACTAMENTE al producto buscado (mismo SKU, misma versión/variante, mismo aspecto físico),
descartando accesorios, modelos hermanos (Pro/Plus/Lite/Gen2) o listados engañosos de resellers.
"""

from __future__ import annotations

import re
from typing import Any

from google.adk.tools.tool_context import ToolContext

from web_scraping.config import (
    SOURCE_TIER_BASE_AUTHORITY,
    SourceTier,
    classify_url_source_tier,
)
from web_scraping.schemas import ConfidenceGrade

# Palabras clave que suelen indicar que un listado es un accesorio o repuesto y NO el producto principal
ACCESSORY_TRAP_KEYWORDS: tuple[str, ...] = (
    "funda para",
    "case for",
    "cover for",
    "protector para",
    "cargador compatible",
    "cable para",
    "adaptador para",
    "repuesto para",
    "replacement for",
    "compatible con",
    "compatible with",
    "soporte para",
    "estuche para",
)

# Modificadores de variante de modelo que cambian completamente el producto si no están en el input
VARIANT_MODIFIERS: tuple[str, ...] = (
    "pro",
    "max",
    "plus",
    "ultra",
    "lite",
    "mini",
    "fe",
    "se",
    "gen 2",
    "gen 3",
    "v2",
    "v3",
    "mk2",
    "mkii",
    "ii",
    "iii",
)


def _normalize_code(code: str) -> str:
    """Normaliza un SKU/MPN eliminando espacios y guiones para comparación canónica."""
    return re.sub(r"[^a-zA-Z0-9]", "", code).upper()


def verify_exact_product_identity(
    expected_name: str,
    expected_sku: str,
    candidate_title: str,
    candidate_sku: str = "",
    candidate_text_snippet: str = "",
) -> dict[str, Any]:
    """Verifica con máxima exigencia si un hallazgo web corresponde exactamente al producto buscado.

    Detecta trampas frecuentes en web scraping:
    - SKUs casi idénticos pero con sufijo de variante distinta.
    - Títulos de resellers que venden un accesorio ("Funda compatible con...").
    - Modelos de la misma familia pero versión distinta (Pro vs Base, Plus vs Lite).
    """
    warnings: list[str] = []
    norm_expected_sku = _normalize_code(expected_sku)
    norm_cand_sku = _normalize_code(candidate_sku)

    title_lower = candidate_title.lower()
    expected_name_lower = expected_name.lower()
    combined_cand_text = f"{candidate_title} {candidate_sku} {candidate_text_snippet}".lower()

    # 1. Validación de SKU exacto
    sku_score = 0.0
    sku_status = "MISSING"
    if norm_expected_sku:
        if norm_cand_sku and norm_cand_sku == norm_expected_sku:
            sku_score = 100.0
            sku_status = "EXACT_MATCH"
        elif expected_sku.lower() in combined_cand_text:
            sku_score = 95.0
            sku_status = "EXACT_MATCH_IN_TEXT"
        elif norm_cand_sku and (
            norm_expected_sku in norm_cand_sku or norm_cand_sku in norm_expected_sku
        ):
            sku_score = 45.0
            sku_status = "PARTIAL_VARIANT_SKU"
            warnings.append(
                f"Alerta de precisión: El SKU reportado ('{candidate_sku}') es una variante parcial "
                f"y NO idéntico al SKU buscado ('{expected_sku}')."
            )
        elif norm_cand_sku and norm_cand_sku != norm_expected_sku:
            sku_score = 0.0
            sku_status = "SKU_MISMATCH"
            warnings.append(
                f"Conflicto crítico de SKU: Se buscó '{expected_sku}' pero la fuente reporta '{candidate_sku}'."
            )
        else:
            sku_score = 40.0
            sku_status = "SKU_NOT_EXPLICIT"
            warnings.append("La página no muestra explícitamente el código SKU; requiere validación visual y de modelo.")

    # 2. Detección de accesorios ("Funda para...", "Compatible con...")
    is_accessory_trap = False
    for kw in ACCESSORY_TRAP_KEYWORDS:
        if kw in title_lower and kw not in expected_name_lower:
            is_accessory_trap = True
            warnings.append(
                f"Falso positivo detectado: El título contiene '{kw}', indicando un accesorio o repuesto."
            )

    # 3. Detección de modificadores de variante conflictivos (ej. input es modelo base y candidato es 'Pro')
    conflicting_variants: list[str] = []
    title_words = set(re.findall(r"\b\w+\b", title_lower))
    expected_words = set(re.findall(r"\b\w+\b", expected_name_lower))
    for mod in VARIANT_MODIFIERS:
        mod_tokens = set(mod.split())
        if mod_tokens.issubset(title_words) and not mod_tokens.issubset(expected_words):
            conflicting_variants.append(mod)
        elif mod_tokens.issubset(expected_words) and not mod_tokens.issubset(title_words):
            conflicting_variants.append(f"falta '{mod}'")

    if conflicting_variants and sku_status not in ("EXACT_MATCH", "EXACT_MATCH_IN_TEXT"):
        warnings.append(
            f"Discrepancia de versión/modelo detectada entre input y título: {conflicting_variants}."
        )

    # Cálculo del puntaje de identidad del producto (0 - 100)
    token_overlap = (
        len(expected_words & title_words) / max(len(expected_words), 1) * 100.0
        if expected_words
        else 50.0
    )

    identity_score = (sku_score * 0.65) + (token_overlap * 0.35)
    if is_accessory_trap:
        identity_score = min(identity_score, 10.0)
    if sku_status == "SKU_MISMATCH":
        identity_score = min(identity_score, 15.0)
    if conflicting_variants and sku_status not in ("EXACT_MATCH", "EXACT_MATCH_IN_TEXT"):
        identity_score = max(0.0, identity_score - 30.0)

    is_exact_product = (
        identity_score >= 75.0
        and not is_accessory_trap
        and sku_status != "SKU_MISMATCH"
    )

    return {
        "is_exact_product": is_exact_product,
        "identity_precision_score": round(identity_score, 2),
        "sku_status": sku_status,
        "sku_score": round(sku_score, 2),
        "is_accessory_trap": is_accessory_trap,
        "conflicting_variants": conflicting_variants,
        "warnings": warnings,
    }


def compute_source_reliability_ranking(
    sources: list[dict[str, Any]],
    expected_name: str,
    expected_sku: str,
    selected_sources: list[str] | None = None,
    brand_domains: list[str] | None = None,
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """Calcula el ranking de confiabilidad de todas las fuentes recolectadas por los motores.

    Filtra las fuentes según la configuración activa (`selected_sources`) y pondera:
    - 45%: Coincidencia exacta de identidad y SKU del producto.
    - 30%: Autoridad del dominio (`official_only` > `trusted_pages` > `third_party_resellers`).
    - 15%: Consistencia con el reconocimiento visual (Google Lens / Gemini Vision).
    - 10%: Nivel de completitud técnica de la información extraída.
    """
    if tool_context is not None and "execution_plan" in tool_context.state:
        plan = tool_context.state["execution_plan"]
        if selected_sources is None:
            selected_sources = plan["config"].get("selected_sources")
        if brand_domains is None:
            brand_domains = plan["config"].get("brand_official_domains")

    allowed_tiers = selected_sources or [
        SourceTier.OFFICIAL_ONLY.value,
        SourceTier.TRUSTED_PAGES.value,
        SourceTier.THIRD_PARTY_RESELLERS.value,
    ]

    ranked_list: list[dict[str, Any]] = []
    rejected_sources: list[dict[str, Any]] = []

    for item in sources:
        url = str(item.get("source_url", "")).strip()
        title = str(item.get("source_title") or item.get("reported_product_name") or "").strip()
        reported_sku = str(item.get("reported_sku_or_mpn", "")).strip()
        snippet = str(item.get("raw_excerpt", "")).strip()
        engines = item.get("discovered_by_engines") or [
            item.get("discovered_by_engine", "google_search")
        ]
        visual_score = float(item.get("visual_match_score", 80.0))
        completeness = float(item.get("data_completeness_score", 75.0))

        tier_enum = classify_url_source_tier(
            url=url,
            product_name=expected_name,
            brand_domains=brand_domains,
        )
        tier_val = str(item.get("source_tier") or tier_enum.value)
        if tier_val not in [t.value for t in SourceTier]:
            tier_val = tier_enum.value

        # Respetar modularidad de fuentes seleccionadas
        if tier_val not in allowed_tiers:
            rejected_sources.append(
                {
                    "source_url": url,
                    "rejection_reason": (
                        f"Fuente clasificada como '{tier_val}', fuera de las fuentes seleccionadas "
                        f"para esta ejecución ({allowed_tiers})."
                    ),
                }
            )
            continue

        identity_check = verify_exact_product_identity(
            expected_name=expected_name,
            expected_sku=expected_sku,
            candidate_title=title,
            candidate_sku=reported_sku,
            candidate_text_snippet=snippet,
        )

        domain_authority = SOURCE_TIER_BASE_AUTHORITY.get(SourceTier(tier_val), 60.0)
        sku_identity_score = identity_check["identity_precision_score"]

        reliability_score = (
            (sku_identity_score * 0.45)
            + (domain_authority * 0.30)
            + (visual_score * 0.15)
            + (completeness * 0.10)
        )

        if not identity_check["is_exact_product"]:
            reliability_score = min(reliability_score, 34.0)
            rejected_sources.append(
                {
                    "source_url": url,
                    "rejection_reason": "; ".join(identity_check["warnings"])
                    or "No superó la verificación de identidad exacta del producto/SKU.",
                }
            )

        ranked_list.append(
            {
                "source_url": url,
                "source_domain": url.split("/")[2] if "://" in url else url,
                "source_tier": tier_val,
                "discovered_by_engines": engines,
                "reliability_score": round(reliability_score, 2),
                "sku_match_score": identity_check["sku_score"],
                "domain_authority_score": domain_authority,
                "data_completeness_score": round(completeness, 2),
                "is_same_exact_product": identity_check["is_exact_product"],
                "ranking_justification": (
                    f"Nivel={tier_val} (Autoridad {domain_authority}), "
                    f"Estado SKU={identity_check['sku_status']} (Identidad {sku_identity_score}%), "
                    f"Consistencia Visual={visual_score}%."
                    + (
                        f" Advertencias: {'; '.join(identity_check['warnings'])}"
                        if identity_check["warnings"]
                        else ""
                    )
                ),
            }
        )

    ranked_list.sort(key=lambda x: x["reliability_score"], reverse=True)
    for idx, entry in enumerate(ranked_list, start=1):
        entry["rank_position"] = idx

    output = {
        "total_evaluated": len(sources),
        "ranked_sources": ranked_list,
        "rejected_false_positives": rejected_sources,
    }

    if tool_context is not None:
        tool_context.state["source_reliability_ranking"] = output

    return output


def evaluate_information_piece_confidence(
    attribute_name: str,
    proposed_value: Any,
    supporting_sources: list[str],
    initial_input_match: str,
    official_page_match: str,
    visual_recognition_match: str,
    highest_source_tier: str = "trusted_pages",
    evaluator_notes: str = "",
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """Evalúa y critica el grado de confianza de cada pieza de información (Triple Validación).

    Compara el atributo frente a:
    1. Input inicial (`initial_input_match`: 'MATCH', 'CONSISTENT', 'NOT_IN_INPUT', 'CONFLICT')
    2. Página oficial (`official_page_match`: 'MATCH', 'CONSISTENT', 'NO_OFFICIAL_DATA', 'CONFLICT')
    3. Reconocimiento visual (`visual_recognition_match`: 'MATCH', 'NOT_APPLICABLE', 'CONFLICT')

    Args:
        attribute_name: Nombre del atributo evaluado (ej. 'sku', 'dimensiones', 'color', 'potencia').
        proposed_value: Valor propuesto para el atributo.
        supporting_sources: Lista de URLs que respaldan este dato.
        initial_input_match: Relación con el input inicial ('MATCH', 'CONSISTENT', 'NOT_IN_INPUT', 'CONFLICT').
        official_page_match: Relación con la página oficial ('MATCH', 'CONSISTENT', 'NO_OFFICIAL_DATA', 'CONFLICT').
        visual_recognition_match: Relación con el análisis visual Google Lens ('MATCH', 'NOT_APPLICABLE', 'CONFLICT').
        highest_source_tier: Nivel de la fuente más confiable que reporta este dato.
        evaluator_notes: Observaciones críticas del Agente Evaluador.
        tool_context: Contexto de herramientas de Google ADK.

    Returns:
        Crítica estructurada con `confidence_score`, `confidence_grade` y decisión de aceptación.
    """
    in_match = initial_input_match.upper().strip()
    off_match = official_page_match.upper().strip()
    vis_match = visual_recognition_match.upper().strip()

    # Cualquier conflicto con el input inicial, la página oficial o la evidencia visual rechaza el dato
    if "CONFLICT" in (in_match, off_match, vis_match):
        score = 10.0
        grade = ConfidenceGrade.REJECTED_MISMATCH
        accepted = False
    else:
        base_tier_score = {
            "official_only": 92.0,
            "trusted_pages": 80.0,
            "third_party_resellers": 65.0,
        }.get(highest_source_tier, 70.0)

        bonus = 0.0
        if in_match == "MATCH":
            bonus += 5.0
        if off_match == "MATCH":
            bonus += 8.0
        if vis_match == "MATCH":
            bonus += 7.0
        if len(supporting_sources) >= 2:
            bonus += 4.0

        score = min(100.0, base_tier_score + bonus)

        if score >= 90.0:
            grade = ConfidenceGrade.CONFIRMED
        elif score >= 75.0:
            grade = ConfidenceGrade.HIGH_CONFIDENCE
        elif score >= 50.0:
            grade = ConfidenceGrade.MEDIUM_CONFIDENCE
        else:
            grade = ConfidenceGrade.LOW_CONFIDENCE

        threshold = 75.0
        if tool_context is not None and "execution_plan" in tool_context.state:
            threshold = float(
                tool_context.state["execution_plan"]["config"].get(
                    "minimum_precision_threshold", 75.0
                )
            )
        accepted = score >= threshold

    critique_record = {
        "attribute_name": attribute_name,
        "proposed_value": proposed_value,
        "supporting_sources": supporting_sources,
        "alignment_with_initial_input": in_match,
        "alignment_with_official_page": off_match,
        "alignment_with_visual_recognition": vis_match,
        "confidence_score": round(score, 2),
        "confidence_grade": grade.value,
        "accepted_for_consolidation": accepted,
        "evaluator_critique": evaluator_notes
        or (
            f"Evaluación triple: Input={in_match}, Oficial={off_match}, Visual={vis_match}. "
            f"Fuente principal={highest_source_tier}. Confianza={round(score, 2)}% ({grade.value})."
        ),
    }

    if tool_context is not None:
        critiques = list(tool_context.state.get("evaluator_critiques", []))
        critiques.append(critique_record)
        tool_context.state["evaluator_critiques"] = critiques

    return critique_record
