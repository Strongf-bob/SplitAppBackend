from collections.abc import Callable
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph


class ReviewState(TypedDict):
    traces: list[dict[str, Any]]
    report: dict[str, Any]


def build_review_graph(
    analyze: Callable[[list[dict[str, Any]]], dict[str, Any]],
):
    """Compile a graph with one read-only analysis node and no action tools."""

    def analyze_traces(state: ReviewState) -> dict[str, Any]:
        report = analyze(state["traces"])
        return {
            "report": {
                "summary": str(report.get("summary", "No summary provided")),
                "findings": list(report.get("findings", [])),
            }
        }

    graph = StateGraph(ReviewState)
    graph.add_node("analyze_traces", analyze_traces)
    graph.add_edge(START, "analyze_traces")
    graph.add_edge("analyze_traces", END)
    return graph.compile()
