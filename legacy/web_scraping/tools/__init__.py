"""Exportación de herramientas modulares para el agente `web_scraping`."""

from web_scraping.tools.config_tools import (
    check_url_allowed_by_config,
    configure_scraping_execution,
    get_active_execution_plan,
)
from web_scraping.tools.evaluation_tools import (
    compute_source_reliability_ranking,
    evaluate_information_piece_confidence,
    verify_exact_product_identity,
)
from web_scraping.tools.scraper_tools import scrape_product_webpage
from web_scraping.tools.vision_lens_tools import (
    analyze_product_image_lens,
    compare_product_images_visually,
    register_visual_lens_profile,
)

__all__ = [
    "configure_scraping_execution",
    "get_active_execution_plan",
    "check_url_allowed_by_config",
    "analyze_product_image_lens",
    "register_visual_lens_profile",
    "compare_product_images_visually",
    "scrape_product_webpage",
    "verify_exact_product_identity",
    "compute_source_reliability_ranking",
    "evaluate_information_piece_confidence",
]
