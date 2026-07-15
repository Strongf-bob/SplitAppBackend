import json
from pathlib import Path

import pytest


DASHBOARD_PATH = (
    Path(__file__).parents[1]
    / "deploy"
    / "observability"
    / "grafana"
    / "dashboards"
    / "splitapp-backend.json"
)


@pytest.fixture(scope="module")
def panels_by_id() -> dict[int, dict]:
    dashboard = json.loads(DASHBOARD_PATH.read_text(encoding="utf-8"))
    return {panel["id"]: panel for panel in dashboard["panels"]}


def test_request_panels_pin_min_step_to_prometheus_scrape_interval(panels_by_id):
    for panel_id in (2, 3, 4, 5, 6, 7, 8):
        assert all(target.get("interval") == "15s" for target in panels_by_id[panel_id]["targets"])


def test_5xx_ratio_matches_product_traffic_and_has_fraction_bounds(panels_by_id):
    panel = panels_by_id[3]
    expression = panel["targets"][0]["expr"]

    assert expression.count('path!="/api/ping"') == 2
    assert expression.count('path!="/api/metrics"') == 2
    assert panel["fieldConfig"]["defaults"]["unit"] == "percentunit"
    assert panel["fieldConfig"]["defaults"]["min"] == 0
    assert panel["fieldConfig"]["defaults"]["max"] == 1


def test_slow_endpoint_table_filters_zero_observation_histograms(panels_by_id):
    panel = panels_by_id[7]
    expression = panel["targets"][0]["expr"]

    assert "and on (path)" in expression
    assert "splitapp_http_request_duration_seconds_count" in expression
    assert "> 0" in expression
    assert panel["fieldConfig"]["defaults"]["noValue"] == "No requests in the last 5m"


def test_panel_titles_describe_the_values_they_show(panels_by_id):
    assert panels_by_id[1]["title"] == "Backend Metrics Target Up"
    assert panels_by_id[6]["title"] == "HTTP Status Codes"
