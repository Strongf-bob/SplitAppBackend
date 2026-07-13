from pathlib import Path


def test_reviewer_compiles_read_only_langgraph_and_returns_normalized_report():
    from monitoring.log_reviewer.reviewer import build_review_graph

    graph = build_review_graph(lambda traces: {"summary": "No critical findings", "findings": []})
    report = graph.invoke({"traces": [{"message": "splitik_review_trace"}]})["report"]

    assert report == {"summary": "No critical findings", "findings": []}


def test_monitoring_compose_keeps_loki_private_and_exposes_only_caddy():
    compose = Path("deploy/monitoring/compose.yaml").read_text()

    assert "log-reviewer" in compose
    assert "loki:" in compose
    assert '"443:443"' in compose
    assert "3100:3100" not in compose
    assert "9090:9090" not in compose


def test_monitoring_grafana_provisions_the_existing_splitapp_dashboard():
    compose = Path("deploy/monitoring/compose.yaml").read_text()

    assert "../observability/grafana/provisioning" in compose
    assert "../observability/grafana/dashboards" in compose
