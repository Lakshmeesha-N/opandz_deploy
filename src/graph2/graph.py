from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from src.graph2.state.schemas import WriterState
from src.graph2.nodes.agent_node import agent_node, TOOLS
from src.graph2.nodes.load_data_node import load_data_node
from pathlib import Path


def _should_continue(state: WriterState) -> str:
    """
    Routing logic after agent_node:

    1. If LLM generated tool_calls → go to tool_node
    2. Otherwise → END
    """

    messages = state.get("messages", [])
    if not messages:
        return END

    last_message = messages[-1]

    # ✅ If LLM wants to call a tool
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tool_node"

    # ✅ Otherwise stop (normal response OR manual tool already handled)
    return END


def build_graph() -> StateGraph:
    """
    Builds the Writer Agent Pipeline (clean, no rendering logic)
    """

    graph = StateGraph(WriterState)

    # 🔹 Nodes
    graph.add_node("load_data_node", load_data_node)
    graph.add_node("agent_node", agent_node)
    graph.add_node("tool_node", ToolNode(TOOLS))

    # 🔹 Entry
    graph.set_entry_point("load_data_node")

    # 🔹 Flow
    graph.add_edge("load_data_node", "agent_node")

    # 🔹 Conditional routing
    graph.add_conditional_edges(
        "agent_node",
        _should_continue,
        {
            "tool_node": "tool_node",
            END: END,
        }
    )

    # 🔹 Tool loop
    graph.add_edge("tool_node", "agent_node")

    return graph.compile()


# 🔹 Graph instance
writer_graph = build_graph()


# 🔹 Optional visualization
if __name__ == "__main__":
    png_bytes = writer_graph.get_graph().draw_mermaid_png()
    output_path = Path("graph2_visualization.png")

    with open(output_path, "wb") as f:
        f.write(png_bytes)

    print(f"✓ Graph visualization saved → {output_path}")