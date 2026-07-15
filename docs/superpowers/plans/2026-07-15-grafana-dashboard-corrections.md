# Grafana Dashboard Corrections Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the SplitApp backend Grafana overview internally consistent and useful under closed-alpha traffic.

**Architecture:** Keep the existing Prometheus metrics and file-provisioned Grafana dashboard. Correct only the dashboard contract: align query sampling, exclude service traffic consistently, constrain ratios, suppress empty histogram quantiles, and use accurate panel labels.

**Tech Stack:** Grafana 11 dashboard JSON, Prometheus/PromQL, pytest.

## Global Constraints

- Backend repository only.
- Preserve unrelated dirty working-tree files.
- Do not commit or push without a separate user request.
- Keep `/api/ping` and `/api/metrics` out of product-traffic panels.

---

### Task 1: Add the dashboard contract regression test

**Files:**
- Create: `tests/test_observability_dashboard.py`
- Test: `tests/test_observability_dashboard.py`

**Interfaces:**
- Consumes: `deploy/observability/grafana/dashboards/splitapp-backend.json`
- Produces: a pytest contract that indexes panels by title and validates their PromQL and display options

- [x] Write tests requiring a `15s` Min step for request panels, a bounded 5xx ratio, a zero-observation guard for slow endpoints, and accurate panel titles.
- [x] Run `./.venv/bin/python -m pytest tests/test_observability_dashboard.py -q` and confirm the tests fail on the current dashboard.

### Task 2: Correct the dashboard configuration

**Files:**
- Modify: `deploy/observability/grafana/dashboards/splitapp-backend.json`

**Interfaces:**
- Consumes: existing `splitapp_http_requests_total` and `splitapp_http_request_duration_seconds_*` metrics
- Produces: provisioned Grafana panels with consistent product-traffic filters and stable low-traffic presentation

- [x] Add `interval: "15s"` to request, status, error-ratio, and latency targets.
- [x] Apply the product-traffic path exclusions to both sides of the 5xx ratio and constrain its display to `0…1`.
- [x] Filter the slow-endpoint p95 vector by a positive histogram count rate so empty windows render no rows instead of `NaN`.
- [x] Rename `Backend Up` to `Backend Metrics Target Up` and `HTTP Status Families` to `HTTP Status Codes`.
- [x] Set the table no-value text to `No requests in the last 5m`.
- [x] Run `./.venv/bin/python -m pytest tests/test_observability_dashboard.py -q` and confirm it passes.

### Task 3: Verify the backend repository

**Files:**
- Verify: `deploy/observability/grafana/dashboards/splitapp-backend.json`
- Verify: `tests/test_observability_dashboard.py`

**Interfaces:**
- Consumes: completed dashboard and regression test
- Produces: evidence that the JSON and repository gates pass

- [x] Run `python3 -m json.tool deploy/observability/grafana/dashboards/splitapp-backend.json >/dev/null`.
- [x] Run `make test`.
- [x] Run `make lint`.
- [x] Run `make format-check`.
- [x] Run `git diff --check` and review the scoped diff.
