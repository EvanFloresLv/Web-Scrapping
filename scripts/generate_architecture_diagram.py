"""Generador de Diagrama de Arquitectura del agente ADK `web_scraping`.

Características del diagrama:
- Usa el icono de **Google Gemini** (`gemini-3.8-flash`) para todos los agentes y procesos agénticos,
  detallando los puntos principales del scope de cada agente.
- Usa los iconos de los productos de Google correspondientes (**Google Search**, **Google Lens**,
  **Vertex AI / Google ADK**, **Cloud Run**).

Ejecución:
    .venv/bin/python scripts/generate_architecture_diagram.py
"""

from __future__ import annotations

from pathlib import Path

from diagrams import Cluster, Diagram, Edge
from diagrams.custom import Custom
from diagrams.gcp.compute import Run
from diagrams.gcp.ml import VertexAI
from diagrams.onprem.client import User
from PIL import Image, ImageDraw


def _create_gemini_icon(path: Path, size: int = 256) -> str:
    """Genera el icono de estrella curva de 4 puntas de Google Gemini con gradiente azul-violeta-rosa."""
    img = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)

    # Fondo circular suave con borde sutil
    margin = 10
    draw.ellipse(
        [margin, margin, size - margin, size - margin],
        fill=(248, 250, 255, 255),
        outline=(210, 227, 252, 255),
        width=4,
    )

    cx, cy = size / 2.0, size / 2.0
    outer_r = size * 0.40
    inner_c = size * 0.085  # Control de curvatura cóncava de la estrella Gemini

    # Crear máscara de la estrella de 4 puntas cóncava de Gemini
    mask = Image.new("L", (size, size), 0)
    m_px = mask.load()
    grad = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    g_px = grad.load()

    for y in range(size):
        for x in range(size):
            dx = abs(x - cx)
            dy = abs(y - cy)
            if dx + dy == 0:
                val = 0.0
            else:
                # Ecuación superelíptica cóncava (astroidal) para la chispa de Gemini
                val = (dx / outer_r) ** 0.58 + (dy / outer_r) ** 0.58
            if val <= 1.0 or (dx < inner_c and dy < inner_c):
                m_px[x, y] = 255
                # Gradiente diagonal Google Blue (#1A73E8) -> Purple (#9334E6) -> Coral/Pink (#E8457C)
                t = (x + y) / (2.0 * size)
                if t < 0.5:
                    u = t * 2.0
                    r = int(26 * (1 - u) + 147 * u)
                    g = int(115 * (1 - u) + 52 * u)
                    b = int(232 * (1 - u) + 230 * u)
                else:
                    u = (t - 0.5) * 2.0
                    r = int(147 * (1 - u) + 232 * u)
                    g = int(52 * (1 - u) + 69 * u)
                    b = int(230 * (1 - u) + 124 * u)
                g_px[x, y] = (r, g, b, 255)

    # Pequeña chispa secundaria arriba a la derecha
    scx, scy = size * 0.76, size * 0.24
    sr = size * 0.11
    for y in range(size):
        for x in range(size):
            dx = abs(x - scx)
            dy = abs(y - scy)
            if (dx / sr) ** 0.6 + (dy / sr) ** 0.6 <= 1.0:
                m_px[x, y] = 255
                g_px[x, y] = (66, 133, 244, 255)

    img.paste(grad, (0, 0), mask)
    img.save(path)
    return str(path)


def _create_google_search_icon(path: Path, size: int = 256) -> str:
    """Genera el icono multicolor 'G' de Google Search."""
    img = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)

    margin = 10
    draw.ellipse(
        [margin, margin, size - margin, size - margin],
        fill=(255, 255, 255, 255),
        outline=(218, 220, 224, 255),
        width=4,
    )

    bbox = [48, 48, size - 48, size - 48]
    width = 34
    # Rojo (arriba), Amarillo (izquierda), Verde (abajo), Azul (derecha)
    draw.arc(bbox, start=215, end=315, fill=(234, 67, 53, 255), width=width)
    draw.arc(bbox, start=145, end=215, fill=(251, 188, 5, 255), width=width)
    draw.arc(bbox, start=45, end=145, fill=(52, 168, 83, 255), width=width)
    draw.arc(bbox, start=350, end=45, fill=(66, 133, 244, 255), width=width)
    # Barra horizontal de la G en azul
    cy = size // 2
    draw.rectangle(
        [cy, cy - width // 2 + 2, size - 50, cy + width // 2 - 2],
        fill=(66, 133, 244, 255),
    )

    img.save(path)
    return str(path)


def _create_google_lens_icon(path: Path, size: int = 256) -> str:
    """Genera el icono oficial de Google Lens (visor en los 4 colores de Google + lente central)."""
    img = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)

    margin = 10
    draw.ellipse(
        [margin, margin, size - margin, size - margin],
        fill=(255, 255, 255, 255),
        outline=(218, 220, 224, 255),
        width=4,
    )

    w = 22
    # Esquina superior izquierda (Azul)
    draw.arc([54, 54, 124, 124], start=180, end=270, fill=(66, 133, 244, 255), width=w)
    draw.rectangle([88, 54, 145, 54 + w], fill=(66, 133, 244, 255))
    draw.rectangle([54, 88, 54 + w, 135], fill=(66, 133, 244, 255))

    # Esquina superior derecha (Rojo)
    draw.arc([132, 54, 202, 124], start=270, end=360, fill=(234, 67, 53, 255), width=w)
    draw.rectangle([115, 54, 168, 54 + w], fill=(234, 67, 53, 255))
    draw.rectangle([202 - w, 88, 202, 135], fill=(234, 67, 53, 255))

    # Esquina inferior izquierda (Amarillo)
    draw.arc([54, 132, 124, 202], start=90, end=180, fill=(251, 188, 5, 255), width=w)
    draw.rectangle([54, 120, 54 + w, 168], fill=(251, 188, 5, 255))
    draw.rectangle([88, 202 - w, 145, 202], fill=(251, 188, 5, 255))

    # Punto central (Azul) y punto inferior derecho (Verde)
    cx, cy = size // 2, size // 2
    draw.ellipse([cx - 26, cy - 26, cx + 26, cy + 26], fill=(66, 133, 244, 255))
    draw.ellipse([160, 160, 198, 198], fill=(52, 168, 83, 255))

    img.save(path)
    return str(path)


def _create_source_badge_icon(
    path: Path, color: tuple[int, int, int], symbol: str, size: int = 256
) -> str:
    """Genera un icono limpio para cada una de las 3 categorías de fuentes configurables."""
    img = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)

    margin = 14
    draw.rounded_rectangle(
        [margin, margin, size - margin, size - margin],
        radius=42,
        fill=(*color, 28),
        outline=(*color, 255),
        width=8,
    )

    cx, cy = size // 2, size // 2
    if symbol == "official":
        # Escudo / Sello verificado oficial
        pts = [
            (cx, 54),
            (size - 62, 82),
            (size - 62, 138),
            (cx, size - 52),
            (62, 138),
            (62, 82),
        ]
        draw.polygon(pts, fill=(*color, 230))
        draw.line(
            [(cx - 24, cy + 4), (cx - 6, cy + 24), (cx + 28, cy - 16)],
            fill=(255, 255, 255, 255),
            width=12,
        )
    elif symbol == "trusted":
        # Globo / Red de catálogos verificados
        r = 66
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(*color, 255), width=10)
        draw.ellipse([cx - r // 2, cy - r, cx + r // 2, cy + r], outline=(*color, 255), width=8)
        draw.line([(cx - r, cy), (cx + r, cy)], fill=(*color, 255), width=8)
    else:
        # Tienda / Marketplace 3rd party
        draw.rounded_rectangle([64, 84, size - 64, size - 64], radius=16, fill=(*color, 230))
        draw.arc([92, 52, size - 92, 116], start=180, end=360, fill=(*color, 255), width=10)

    img.save(path)
    return str(path)


def build_diagram() -> str:
    """Genera el diagrama PNG de arquitectura del agente ADK `web_scraping`."""
    base_dir = Path(__file__).resolve().parent.parent
    output_dir = base_dir / "docs"
    icons_dir = output_dir / "icons"
    icons_dir.mkdir(parents=True, exist_ok=True)

    gemini_icon = _create_gemini_icon(icons_dir / "gemini.png")
    gsearch_icon = _create_google_search_icon(icons_dir / "google_search.png")
    glens_icon = _create_google_lens_icon(icons_dir / "google_lens.png")
    official_icon = _create_source_badge_icon(
        icons_dir / "source_official.png", (26, 115, 232), "official"
    )
    trusted_icon = _create_source_badge_icon(
        icons_dir / "source_trusted.png", (30, 142, 62), "trusted"
    )
    third_party_icon = _create_source_badge_icon(
        icons_dir / "source_3rd_party.png", (249, 171, 0), "3rd_party"
    )

    output_base = str(output_dir / "web_scraping_gcp_architecture")

    graph_attr = {
        "fontsize": "20",
        "fontname": "Sans-Serif",
        "bgcolor": "#FFFFFF",
        "pad": "0.6",
        "nodesep": "0.60",
        "ranksep": "1.05",
        "splines": "ortho",
    }

    node_attr = {
        "fontname": "Sans-Serif",
        "fontsize": "10",
    }

    with Diagram(
        "Google ADK — Arquitectura Agéntica: web_scraping (Modelo: gemini-3.8-flash)",
        filename=output_base,
        outformat="png",
        show=False,
        direction="LR",
        graph_attr=graph_attr,
        node_attr=node_attr,
    ):
        user_input = User(
            "Input por Ejecución\n"
            "• nombre, sku, descripcion, imagen\n"
            "• Selección modular de Fuentes\n"
            "• Selección modular de Motores"
        )

        with Cluster("Google Cloud / Google ADK Runtime (Vertex AI + Cloud Run)"):
            with Cluster("Plataforma Google Cloud"):
                adk_runtime = Run("Cloud Run / ADK Web\n(Servidor de Ejecución)")
                vertex_platform = VertexAI("Vertex AI / Google GenAI\n(Proveedor Gemini 3.8 Flash)")

            root_agent = Custom(
                "AGENTE RAÍZ ADK: web_scraping\n"
                "[Modelo: gemini-3.8-flash]\n"
                "• Configura fuentes y motores por ejecución\n"
                "• Orquesta sub-agentes activos\n"
                "• Garantiza prioridad máxima en SKU exacto",
                gemini_icon,
            )

            with Cluster(
                "1. Sub-Agentes de Búsqueda e Investigación (Seleccionables 1, 2 o los 3)"
            ):
                search_agent = Custom(
                    "SUB-AGENTE: google_search_engine\n"
                    "[Modelo: gemini-3.8-flash]\n"
                    "• Consultas por nivel de fuente activo\n"
                    "• Verificación primaria de SKU/MPN\n"
                    "• Extracción de atributos y URLs",
                    gemini_icon,
                )
                lens_agent = Custom(
                    "SUB-AGENTE: google_lens_engine\n"
                    "[Modelo: gemini-3.8-flash]\n"
                    "• OCR de SKU/etiquetas en imagen/caja\n"
                    "• Extracción de huella visual física\n"
                    "• Comparación visual input vs foto web",
                    gemini_icon,
                )
                deep_agent = Custom(
                    "SUB-AGENTE: deep_research_engine\n"
                    "[Modelo: gemini-3.8-flash]\n"
                    "• Investigación iterativa multi-paso\n"
                    "• Scraping JSON-LD, OpenGraph y tablas\n"
                    "• Descarte de variantes y accesorios",
                    gemini_icon,
                )

            with Cluster("Productos de Google Invocados"):
                google_search_prod = Custom(
                    "Google Search\n(Grounding Nativo ADK)",
                    gsearch_icon,
                )
                google_lens_prod = Custom(
                    "Google Lens / Vision\n(Búsqueda y Cruce Visual)",
                    glens_icon,
                )

            with Cluster(
                "2. Fuentes de Información Modulares (Seleccionables por separado o juntas)"
            ):
                src_official = Custom(
                    "Opción 1: official_only\n"
                    "• Solo Página Oficial de la Marca\n"
                    "• Ficha técnica canónica (Ground Truth)",
                    official_icon,
                )
                src_trusted = Custom(
                    "Opción 2: trusted_pages\n"
                    "• Distribuidores Autorizados\n"
                    "• Catálogos Técnicos (Icecat, GS1, BHPhoto)",
                    trusted_icon,
                )
                src_third = Custom(
                    "Opción 3: third_party_resellers (eth_party)\n"
                    "• Amazon, Mercado Libre, eBay\n"
                    "• Marketplaces y Resellers Externos",
                    third_party_icon,
                )

            with Cluster("3. Pipeline Agéntico de Ranking, Evaluación Crítica y Consolidación"):
                ranking_agent = Custom(
                    "SUB-AGENTE: reliability_ranking_engine\n"
                    "[Modelo: gemini-3.8-flash]\n"
                    "• Analiza salidas de todos los motores\n"
                    "• Ranking de confiabilidad (0-100)\n"
                    "• Pondera: 45% SKU + 30% Dominio + 15% Visual",
                    gemini_icon,
                )
                evaluator_agent = Custom(
                    "AGENTE EVALUADOR: precision_evaluator_engine\n"
                    "[Modelo: gemini-3.8-flash]\n"
                    "• Critica confianza de cada dato vs:\n"
                    "  1) Input Inicial (nombre, SKU, desc)\n"
                    "  2) Página Oficial (Ground Truth)\n"
                    "  3) Reconocimiento Visual (Lens)\n"
                    "• Rechaza falsos positivos (REJECTED_MISMATCH)",
                    gemini_icon,
                )
                consolidator_agent = Custom(
                    "SUB-AGENTE: consolidator_engine\n"
                    "[Modelo: gemini-3.8-flash]\n"
                    "• Consolida todo en un único output final\n"
                    "• Ficha Maestra solo con datos confirmados\n"
                    "• Incluye Ranking y Matriz del Evaluador",
                    gemini_icon,
                )

        # Conexiones de entrada y plataforma
        user_input >> Edge(label="Input + Config", color="#1A73E8", style="bold") >> adk_runtime
        adk_runtime >> Edge(color="#1A73E8", style="bold") >> root_agent
        (
            vertex_platform
            >> Edge(style="dashed", color="#9334E6", label="gemini-3.8-flash")
            >> root_agent
        )

        # Orquestador a los 3 Sub-Agentes de Motores
        (
            root_agent
            >> Edge(label="Motor 1 (Opcional)", color="#1E8E3E", style="bold")
            >> search_agent
        )
        root_agent >> Edge(label="Motor 2 (Opcional)", color="#1E8E3E", style="bold") >> lens_agent
        root_agent >> Edge(label="Motor 3 (Opcional)", color="#1E8E3E", style="bold") >> deep_agent

        # Sub-Agentes a Productos de Google
        search_agent >> Edge(color="#4285F4") >> google_search_prod
        lens_agent >> Edge(color="#EA4335") >> google_lens_prod
        deep_agent >> Edge(color="#4285F4", style="dashed") >> google_search_prod

        # Productos/Motores hacia Fuentes Modulares
        for node in (google_search_prod, google_lens_prod, deep_agent):
            node >> Edge(color="#F9AB00") >> src_official
            node >> Edge(color="#F9AB00") >> src_trusted
            node >> Edge(color="#F9AB00") >> src_third

        # Fuentes al Sub-Agente de Ranking de Confiabilidad
        for src in (src_official, src_trusted, src_third):
            src >> Edge(color="#1A73E8") >> ranking_agent

        # Flujo secuencial de Ranking -> Evaluador Crítico -> Consolidador
        (
            ranking_agent
            >> Edge(label="Fuentes Rankeadas\n(0-100)", color="#9334E6", style="bold")
            >> evaluator_agent
        )
        (
            evaluator_agent
            >> Edge(label="Datos Auditados\n(Triple Validación)", color="#D93025", style="bold")
            >> consolidator_agent
        )

    return f"{output_base}.png"


if __name__ == "__main__":
    out_file = build_diagram()
    print(f"Diagrama generado exitosamente en: {out_file}")
