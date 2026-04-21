# src/graph1/graph.py
import sys
from pathlib import Path

if __package__ in {None, ""}:
    # When this file is run directly, add the project root so `src.*` imports resolve.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from langgraph.graph import StateGraph, END
from src.graph1.state.schemas               import GlobalState
from src.graph1.nodes.pdf_input_node        import pdf_input_node
from src.graph1.nodes.pymupdf_node          import pymupdf_node
from src.graph1.nodes.image_conversion_node import image_conversion_node
from src.graph1.nodes.lilt_node             import lilt_node
from src.graph1.nodes.yolo_node             import yolo_node
from src.graph1.nodes.merge_node            import merge_node
from src.graph1.nodes.blueprint_node        import blueprint_node


def build_graph() -> StateGraph:
    """
    Build and compile Graph 1 — Extraction Pipeline.

    Parallel chains:
        Chain 1: pdf_input → pymupdf → lilt → merge
        Chain 2: pdf_input → image_conversion → yolo → merge

    Sequential after merge:
        merge → blueprint → END
    """

    graph = StateGraph(GlobalState)

    # ── Register nodes ────────────────────────
    graph.add_node("pdf_input_node",        pdf_input_node)
    graph.add_node("pymupdf_node",          pymupdf_node)
    graph.add_node("image_conversion_node", image_conversion_node)
    graph.add_node("lilt_node",             lilt_node)
    graph.add_node("yolo_node",             yolo_node)
    graph.add_node("merge_node",            merge_node)
    graph.add_node("blueprint_node",        blueprint_node)

    # ── Entry point ───────────────────────────
    graph.set_entry_point("pdf_input_node")

    # ── Chain 1: pymupdf → lilt ───────────────
    graph.add_edge("pdf_input_node", "pymupdf_node")
    graph.add_edge("pymupdf_node",   "lilt_node")

    # ── Chain 2: image_conversion → yolo ──────
    graph.add_edge("pdf_input_node",        "image_conversion_node")
    graph.add_edge("image_conversion_node", "yolo_node")

    # ── Both chains → merge ───────────────────
    graph.add_edge("lilt_node", "merge_node")
    graph.add_edge("yolo_node", "merge_node")

    # ── Sequential after merge ────────────────
    graph.add_edge("merge_node",     "blueprint_node")
    graph.add_edge("blueprint_node", END)

    return graph.compile()


# ── Compiled graph instance ───────────────────
# Import this anywhere to invoke the graph
extraction_graph = build_graph()


# ── Visualize ─────────────────────────────────
if __name__ == "__main__":
    png_bytes   = extraction_graph.get_graph().draw_mermaid_png()
    output_path = Path("graph1_visualization.png")

    with open(output_path, "wb") as f:
        f.write(png_bytes)

    print(f"✓ Graph visualization saved → {output_path}")
