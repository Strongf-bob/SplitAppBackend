import asyncio
from contextlib import asynccontextmanager
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from fastapi import FastAPI, HTTPException
from prometheus_client import Gauge, make_asgi_app

from reviewer import build_review_graph


REPORTS_PATH = Path(os.getenv("LOG_REVIEWER_REPORTS_PATH", "/data/reports.json"))
LAST_RUN = Gauge("splitapp_log_reviewer_last_run_timestamp", "Unix timestamp of the last review")
FINDINGS = Gauge("splitapp_log_reviewer_findings", "Findings in the latest review")


def _reports() -> list[dict[str, Any]]:
    if not REPORTS_PATH.exists():
        return []
    return json.loads(REPORTS_PATH.read_text())


def _save(report: dict[str, Any]) -> None:
    REPORTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    reports = _reports()
    reports.insert(0, report)
    REPORTS_PATH.write_text(json.dumps(reports[:100], ensure_ascii=False, default=str))


def _analyze(traces: list[dict[str, Any]]) -> dict[str, Any]:
    base_url = os.environ["LOG_REVIEWER_LLM_BASE_URL"].rstrip("/")
    payload = {
        "model": os.getenv("LOG_REVIEWER_MODEL", "deepseek-v4-pro"),
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "You are a read-only production log reviewer. Return JSON with summary and findings. Never propose automatic actions."},
            {"role": "user", "content": json.dumps(traces, ensure_ascii=False)},
        ],
    }
    response = httpx.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {os.environ['LOG_REVIEWER_LLM_API_KEY']}"},
        json=payload,
        timeout=60,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    return json.loads(content)


def _traces() -> list[dict[str, Any]]:
    now = datetime.now(UTC)
    start = now - timedelta(hours=24)
    response = httpx.get(
        f"{os.getenv('LOKI_URL', 'http://loki:3100').rstrip('/')}/loki/api/v1/query_range",
        params={"query": '{message="splitik_review_trace"}', "start": str(int(start.timestamp() * 1e9)), "end": str(int(now.timestamp() * 1e9))},
        timeout=30,
    )
    response.raise_for_status()
    return [json.loads(value) for stream in response.json()["data"]["result"] for _, value in stream["values"]]


def run_review() -> dict[str, Any]:
    graph = build_review_graph(_analyze)
    report = graph.invoke({"traces": _traces()})["report"]
    report["created_at"] = datetime.now(UTC).isoformat()
    _save(report)
    LAST_RUN.set(datetime.now(UTC).timestamp())
    FINDINGS.set(len(report["findings"]))
    return report


async def _daily_review_loop() -> None:
    timezone = ZoneInfo("Europe/Moscow")
    while True:
        now = datetime.now(timezone)
        target = now.replace(hour=8, minute=30, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())
        try:
            await asyncio.to_thread(run_review)
        except Exception:
            # The service remains available and Prometheus observes the missing fresh report.
            pass


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(_daily_review_loop())
    yield
    task.cancel()


app = FastAPI(title="SplitApp Log Reviewer", lifespan=lifespan)


@app.get("/api/reports/latest")
def latest_report() -> dict[str, Any]:
    reports = _reports()
    if not reports:
        raise HTTPException(status_code=404, detail="No review report yet.")
    return reports[0]


@app.get("/api/reports")
def list_reports(limit: int = 20) -> list[dict[str, Any]]:
    return _reports()[:max(1, min(limit, 100))]


@app.post("/internal/run-review")
def trigger_review() -> dict[str, Any]:
    return run_review()


app.mount("/metrics", make_asgi_app())
