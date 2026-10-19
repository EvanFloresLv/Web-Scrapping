"""Pruebas unitarias y de integración modular para el agente ADK `web_scraping`."""

from __future__ import annotations

from web_scraping.config import (
    ExecutionConfig,
    SearchEngine,
    SourceTier,
    classify_url_source_tier,
)
from web_scraping.schemas import ConfidenceGrade
from web_scraping.tools.config_tools import configure_scraping_execution
from web_scraping.tools.evaluation_tools import (
    compute_source_reliability_ranking,
    evaluate_information_piece_confidence,
    verify_exact_product_identity,
)


def test_source_tiers_single_and_combined():
    """Verifica que las 3 opciones de fuentes funcionen por separado o juntas."""
    # 1. Solo página oficial
    cfg_official = ExecutionConfig(selected_sources=["official_only"])
    assert cfg_official.selected_sources == [SourceTier.OFFICIAL_ONLY]

    # 2. Solo páginas confiables
    cfg_trusted = ExecutionConfig(selected_sources=["paginas_confiables"])
    assert cfg_trusted.selected_sources == [SourceTier.TRUSTED_PAGES]

    # 3. Solo 3rd party / resellers (usando alias eth_party)
    cfg_third = ExecutionConfig(selected_sources=["eth_party"])
    assert cfg_third.selected_sources == [SourceTier.THIRD_PARTY_RESELLERS]

    # 4. Combinación de 2 (oficial + confiables)
    cfg_two = ExecutionConfig(selected_sources=["official_only", "trusted_pages"])
    assert cfg_two.selected_sources == [SourceTier.OFFICIAL_ONLY, SourceTier.TRUSTED_PAGES]

    # 5. Las 3 juntas
    cfg_all = ExecutionConfig(
        selected_sources=["official_only", "trusted_pages", "third_party_resellers"]
    )
    assert len(cfg_all.selected_sources) == 3


def test_search_engines_single_and_combined():
    """Verifica que los 3 motores de búsqueda puedan seleccionarse uno o todos."""
    # Solo Google Search
    cfg_gs = ExecutionConfig(selected_engines=["google_search"])
    assert cfg_gs.selected_engines == [SearchEngine.GOOGLE_SEARCH]

    # Solo Google Lens
    cfg_lens = ExecutionConfig(selected_engines=["google_lens"])
    assert cfg_lens.selected_engines == [SearchEngine.GOOGLE_LENS]

    # Solo Deep Research
    cfg_dr = ExecutionConfig(selected_engines=["deep_research"])
    assert cfg_dr.selected_engines == [SearchEngine.DEEP_RESEARCH]

    # Combinados (Google Lens + Deep Research)
    cfg_combo = ExecutionConfig(selected_engines=["google_lens", "deep_research"])
    assert cfg_combo.selected_engines == [
        SearchEngine.GOOGLE_LENS,
        SearchEngine.DEEP_RESEARCH,
    ]


def test_configure_scraping_execution_tool():
    """Verifica la herramienta de configuración por ejecución desde parámetros de input."""
    res = configure_scraping_execution(
        nombre="Sony WH-1000XM5",
        sku="WH1000XM5/B",
        descripcion="Audífonos inalámbricos con noise cancelling color negro",
        imagen="https://example.com/wh1000xm5.jpg",
        fuentes=["official_only", "eth_party"],
        motores=["google_search", "google_lens"],
        dominios_oficiales=["sony.com", "sony.com.mx"],
    )
    assert res["status"] == "CONFIGURED"
    plan = res["execution_plan"]
    assert plan["config"]["selected_sources"] == ["official_only", "third_party_resellers"]
    assert plan["config"]["selected_engines"] == ["google_search", "google_lens"]
    assert plan["engines_to_invoke"]["run_google_search"] is True
    assert plan["engines_to_invoke"]["run_google_lens"] is True
    assert plan["engines_to_invoke"]["run_deep_research"] is False


def test_url_source_tier_classification():
    """Verifica la clasificación correcta entre página oficial, confiable y 3rd party reseller."""
    assert (
        classify_url_source_tier(
            "https://www.sony.com/electronics/headband-headphones/wh-1000xm5",
            product_name="Sony WH-1000XM5",
            brand_domains=["sony.com"],
        )
        == SourceTier.OFFICIAL_ONLY
    )
    assert (
        classify_url_source_tier(
            "https://www.bhphotovideo.com/c/product/sony_wh1000xm5",
            product_name="Sony WH-1000XM5",
        )
        == SourceTier.TRUSTED_PAGES
    )
    assert (
        classify_url_source_tier(
            "https://articulo.mercadolibre.com.mx/MLM-12345-sony-wh1000xm5",
            product_name="Sony WH-1000XM5",
        )
        == SourceTier.THIRD_PARTY_RESELLERS
    )
    assert (
        classify_url_source_tier(
            "https://www.amazon.com.mx/dp/B09XS7JWHH",
            product_name="Sony WH-1000XM5",
        )
        == SourceTier.THIRD_PARTY_RESELLERS
    )


def test_verify_exact_product_identity_precision():
    """Verifica que la máxima prioridad (precisión del producto/SKU exacto) detecte falsos positivos."""
    # Caso 1: Producto exacto y mismo SKU
    exact = verify_exact_product_identity(
        expected_name="Logitech MX Master 3S",
        expected_sku="910-006556",
        candidate_title="Mouse Inalámbrico Logitech MX Master 3S Grafito - 910-006556",
        candidate_sku="910-006556",
    )
    assert exact["is_exact_product"] is True
    assert exact["identity_precision_score"] >= 85.0

    # Caso 2: Trampa de accesorio ("Estuche rígido compatible con Logitech MX Master 3S")
    accessory = verify_exact_product_identity(
        expected_name="Logitech MX Master 3S",
        expected_sku="910-006556",
        candidate_title="Estuche para Mouse compatible con Logitech MX Master 3S",
        candidate_sku="CASE-MX3S",
    )
    assert accessory["is_exact_product"] is False
    assert accessory["is_accessory_trap"] is True
    assert accessory["identity_precision_score"] <= 15.0

    # Caso 3: SKU de otro modelo/color distinto
    wrong_sku = verify_exact_product_identity(
        expected_name="Apple iPhone 15 128GB",
        expected_sku="MTP03E/A",
        candidate_title="Apple iPhone 15 Pro Max 256GB",
        candidate_sku="MU773E/A",
    )
    assert wrong_sku["is_exact_product"] is False
    assert wrong_sku["sku_status"] == "SKU_MISMATCH"


def test_source_reliability_ranking_and_filtering():
    """Verifica el ranking de confiabilidad de fuentes y el filtrado modular."""
    sources = [
        {
            "source_url": "https://articulo.mercadolibre.com.mx/MLM-111",
            "source_title": "Audifonos Sony WH-1000XM5 Negro SKU WH1000XM5/B",
            "reported_sku_or_mpn": "WH1000XM5/B",
            "visual_match_score": 90.0,
            "data_completeness_score": 70.0,
        },
        {
            "source_url": "https://www.sony.com/es/wh-1000xm5",
            "source_title": "Sony WH-1000XM5 Wireless Noise Cancelling Headphones WH1000XM5/B",
            "reported_sku_or_mpn": "WH1000XM5/B",
            "visual_match_score": 98.0,
            "data_completeness_score": 95.0,
        },
        {
            "source_url": "https://www.bhphotovideo.com/c/product/sony-xm5",
            "source_title": "Sony WH-1000XM5 Headphones (Black) MPN WH1000XM5/B",
            "reported_sku_or_mpn": "WH1000XM5/B",
            "visual_match_score": 95.0,
            "data_completeness_score": 90.0,
        },
    ]

    ranking_res = compute_source_reliability_ranking(
        sources=sources,
        expected_name="Sony WH-1000XM5",
        expected_sku="WH1000XM5/B",
        selected_sources=["official_only", "trusted_pages", "third_party_resellers"],
        brand_domains=["sony.com"],
    )

    ranked = ranking_res["ranked_sources"]
    assert len(ranked) == 3
    # La página oficial debe quedar en #1, luego confiable en #2 y luego reseller en #3
    assert ranked[0]["source_tier"] == "official_only"
    assert ranked[1]["source_tier"] == "trusted_pages"
    assert ranked[2]["source_tier"] == "third_party_resellers"
    assert ranked[0]["reliability_score"] > ranked[1]["reliability_score"] > ranked[2]["reliability_score"]

    # Ahora probamos seleccionando SOLO 'official_only': debe filtrar las demás
    only_official_res = compute_source_reliability_ranking(
        sources=sources,
        expected_name="Sony WH-1000XM5",
        expected_sku="WH1000XM5/B",
        selected_sources=["official_only"],
        brand_domains=["sony.com"],
    )
    assert len(only_official_res["ranked_sources"]) == 1
    assert only_official_res["ranked_sources"][0]["source_tier"] == "official_only"
    assert len(only_official_res["rejected_false_positives"]) == 2


def test_triple_check_evaluator_critique():
    """Verifica la crítica del Agente Evaluador respecto a Input Inicial, Oficial y Visual."""
    # Dato confirmado por los 3 pilares
    confirmed = evaluate_information_piece_confidence(
        attribute_name="Autonomía de batería",
        proposed_value="30 horas con ANC activado",
        supporting_sources=["https://www.sony.com/es/wh-1000xm5"],
        initial_input_match="CONSISTENT",
        official_page_match="MATCH",
        visual_recognition_match="MATCH",
        highest_source_tier="official_only",
    )
    assert confirmed["confidence_grade"] == ConfidenceGrade.CONFIRMED.value
    assert confirmed["accepted_for_consolidation"] is True

    # Dato de un reseller que contradice el reconocimiento visual (ej. puerto incorrecto)
    rejected = evaluate_information_piece_confidence(
        attribute_name="Puerto de carga",
        proposed_value="Micro-USB",
        supporting_sources=["https://www.ebay.com/itm/fake-xm5"],
        initial_input_match="NOT_IN_INPUT",
        official_page_match="CONFLICT",
        visual_recognition_match="CONFLICT",
        highest_source_tier="third_party_resellers",
        evaluator_notes="En la imagen del producto y ficha oficial el puerto es USB-C, no Micro-USB.",
    )
    assert rejected["confidence_grade"] == ConfidenceGrade.REJECTED_MISMATCH.value
    assert rejected["accepted_for_consolidation"] is False


def test_adk_root_agent_registration():
    """Verifica que el agente raíz `web_scraping` y sus sub-agentes ADK carguen correctamente."""
    from web_scraping import root_agent, web_scraping

    assert root_agent.name == "web_scraping"
    assert web_scraping is root_agent

    tool_names = [getattr(t, "name", getattr(t, "__name__", "")) for t in root_agent.tools]
    expected_tools = {
        "configure_scraping_execution",
        "get_active_execution_plan",
        "check_url_allowed_by_config",
        "google_search_engine",
        "google_lens_engine",
        "deep_research_engine",
        "reliability_ranking_engine",
        "precision_evaluator_engine",
        "consolidator_engine",
    }
    assert expected_tools.issubset(set(tool_names))
