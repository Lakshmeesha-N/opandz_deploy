from src.graph2.state.schemas import WriterState


def load_data_node(state: WriterState) -> dict:
    return {
        "request_id": state["request_id"],
        "user_query": state["user_query"],
        "filled_placeholders": state["filled_placeholders"],
        "messages": state.get("messages", []),
        "errors": state.get("errors", []),
    }