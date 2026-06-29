#!/usr/bin/env python3
"""Publish Alibaba OpenCodeReview JSON findings as a GitHub PR review."""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SEVERITY_ORDER = {"critical": 5, "high": 4, "medium": 3, "low": 2, "style": 1}
DEFAULT_BLOCKING = {"critical", "high"}
COMMENT_MARKER = "<!-- opencode-review -->"
MAX_INLINE_COMMENTS = 80


@dataclass(frozen=True)
class Finding:
    path: str | None
    start_line: int | None
    line: int | None
    severity: str
    title: str
    body: str


@dataclass(frozen=True)
class ReviewResult:
    findings: list[Finding]
    status: str | None
    message: str | None


def log(message: str) -> None:
    print(f"[opencode-review] {message}", flush=True)


def load_json(path: Path) -> Any:
    if not path.exists():
        log(f"OCR output file does not exist: {path}")
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        log(f"Unable to read OCR output file {path}: {exc}")
        return None
    if not text:
        log("OCR output file is empty.")
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        log(f"OCR output is not valid JSON: {exc}")
        return None


def first_string(mapping: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def first_int(mapping: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
    return None


def normalize_severity(raw: Any, text: str = "") -> str:
    candidates: list[str] = []
    if isinstance(raw, str):
        candidates.append(raw)
    candidates.extend(re.findall(r"\b(critical|high|medium|low|style)\b", text, re.I))
    for candidate in candidates:
        normalized = candidate.strip().lower()
        if normalized in SEVERITY_ORDER:
            return normalized
    return "medium"


def finding_from_dict(item: dict[str, Any]) -> Finding | None:
    path = first_string(
        item,
        (
            "path",
            "file",
            "filename",
            "filePath",
            "file_path",
            "relativePath",
            "relative_path",
        ),
    )
    start_line = first_int(item, ("start_line", "startLine", "start", "from_line", "fromLine"))
    line = first_int(
        item,
        (
            "end_line",
            "endLine",
            "line",
            "lineNumber",
            "line_number",
            "newLine",
            "new_line",
            "position",
        ),
    )
    if line is None:
        line = start_line
    title = first_string(item, ("title", "rule", "category", "type", "summary")) or "OpenCodeReview finding"
    message = first_string(
        item,
        (
            "body",
            "message",
            "comment",
            "description",
            "content",
            "detail",
            "details",
            "recommendation",
            "suggestion",
        ),
    )
    if message is None:
        nested_messages = [
            value.strip()
            for value in item.values()
            if isinstance(value, str) and len(value.strip()) > 20
        ]
        message = "\n\n".join(nested_messages[:3])

    if not message:
        return None

    has_location = path is not None or line is not None or start_line is not None
    has_explicit_finding_signal = any(
        key in item
        for key in (
            "severity",
            "level",
            "priority",
            "rule",
            "category",
            "recommendation",
            "suggestion",
        )
    )
    if not has_location and not has_explicit_finding_signal:
        return None

    severity = normalize_severity(
        item.get("severity") or item.get("level") or item.get("priority"),
        f"{title}\n{message}",
    )
    return Finding(
        path=path,
        start_line=start_line,
        line=line,
        severity=severity,
        title=title,
        body=message,
    )


def extract_findings(data: Any) -> list[Finding]:
    findings: list[Finding] = []

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for child in node:
                walk(child)
            return
        if not isinstance(node, dict):
            return

        candidate = finding_from_dict(node)
        if candidate is not None:
            findings.append(candidate)

        for key in (
            "findings",
            "issues",
            "comments",
            "reviews",
            "results",
            "data",
            "items",
            "problems",
            "diagnostics",
        ):
            if key in node:
                walk(node[key])

    walk(data)

    unique: list[Finding] = []
    seen: set[tuple[str | None, int | None, str, str]] = set()
    for finding in findings:
        identity = (finding.path, finding.line, finding.severity, finding.body[:300])
        if identity not in seen:
            seen.add(identity)
            unique.append(finding)
    return unique


def parse_review_result(data: Any) -> ReviewResult:
    status = None
    message = None
    if isinstance(data, dict):
        status = first_string(data, ("status",))
        message = first_string(data, ("message", "summary"))
    return ReviewResult(findings=extract_findings(data), status=status, message=message)


def github_request(method: str, url: str, token: str, payload: dict[str, Any] | None = None) -> Any:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API {method} {url} failed: {exc.code} {error_body}") from exc


def collect_changed_lines(api_url: str, repo: str, pr_number: str, token: str) -> set[tuple[str, int]]:
    changed: set[tuple[str, int]] = set()
    page = 1
    while True:
        url = f"{api_url}/repos/{repo}/pulls/{pr_number}/files?per_page=100&page={page}"
        files = github_request("GET", url, token)
        if not files:
            break
        for file_info in files:
            filename = file_info.get("filename")
            patch = file_info.get("patch", "")
            if isinstance(filename, str) and isinstance(patch, str):
                changed.update(parse_patch_changed_lines(filename, patch))
        if len(files) < 100:
            break
        page += 1
    return changed


def parse_patch_changed_lines(filename: str, patch: str) -> set[tuple[str, int]]:
    changed: set[tuple[str, int]] = set()
    new_line = 0
    for row in patch.splitlines():
        header = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", row)
        if header:
            new_line = int(header.group(1))
            continue
        if row.startswith("+") and not row.startswith("+++"):
            changed.add((filename, new_line))
            new_line += 1
        elif row.startswith("-") and not row.startswith("---"):
            continue
        else:
            new_line += 1
    return changed


def format_finding_body(finding: Finding) -> str:
    location = f"{finding.path}:{finding.line}" if finding.path and finding.line else "summary"
    return (
        f"{COMMENT_MARKER}\n"
        f"**Severity:** `{finding.severity}`\n\n"
        f"**{finding.title}**\n\n"
        f"{finding.body}\n\n"
        f"_OpenCodeReview location: `{location}`_"
    )


def build_summary(result: ReviewResult, inline_count: int, blocking: set[str]) -> str:
    findings = result.findings
    counts = {severity: 0 for severity in SEVERITY_ORDER}
    for finding in findings:
        counts[finding.severity] = counts.get(finding.severity, 0) + 1
    blocking_count = sum(1 for finding in findings if finding.severity in blocking)

    lines = [
        COMMENT_MARKER,
        "## OpenCodeReview summary",
        "",
        f"Findings: {len(findings)}",
        f"Inline comments posted: {inline_count}",
        f"Blocking findings: {blocking_count}",
    ]
    if result.status:
        lines.append(f"Status: `{result.status}`")
    if not findings:
        if result.message:
            lines.extend(["", f"OpenCodeReview: {result.message}"])
        lines.extend(["", "**Итог:** все нормально, блокирующих замечаний нет."])
        return "\n".join(lines)

    lines.extend(["", "| Severity | Count | Blocks merge |", "| --- | ---: | --- |"])
    for severity in ("critical", "high", "medium", "low", "style"):
        blocks = "yes" if severity in blocking else "no"
        lines.append(f"| {severity} | {counts.get(severity, 0)} | {blocks} |")

    lines.extend(["", "### Findings"])
    for finding in findings[:50]:
        location = f"{finding.path}:{finding.line}" if finding.path and finding.line else "summary"
        lines.append(f"- `{finding.severity}` `{location}` - {finding.title}")
    if len(findings) > 50:
        lines.append(f"- ...and {len(findings) - 50} more findings. See the uploaded artifact.")
    return "\n".join(lines)


def main() -> int:
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    output_file = Path(os.environ.get("OCR_OUTPUT_FILE", "opencode-review.json"))
    blocking = {
        severity.strip().lower()
        for severity in os.environ.get("OCR_BLOCKING_SEVERITIES", "critical,high").split(",")
        if severity.strip()
    } or DEFAULT_BLOCKING

    if not token or not repo or not event_path:
        log("Missing GITHUB_TOKEN, GITHUB_REPOSITORY, or GITHUB_EVENT_PATH.")
        return 1

    try:
        event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log(f"Unable to read GitHub event payload: {exc}")
        return 1

    pull_request = event.get("pull_request") or {}
    pr_number = str(pull_request.get("number") or event.get("number") or "")
    commit_id = ((pull_request.get("head") or {}).get("sha")) or os.environ.get("GITHUB_SHA")
    if not pr_number or not commit_id:
        log("This script must run on a pull_request event with a head SHA.")
        return 1

    result = parse_review_result(load_json(output_file))
    findings = result.findings
    log(f"Extracted {len(findings)} finding(s) from {output_file}.")

    try:
        changed_lines = collect_changed_lines(api_url, repo, pr_number, token)
        log(f"Loaded {len(changed_lines)} changed line(s) from the PR diff.")
    except RuntimeError as exc:
        log(str(exc))
        changed_lines = set()

    comments: list[dict[str, Any]] = []
    for finding in findings:
        if len(comments) >= MAX_INLINE_COMMENTS:
            break
        if finding.path and finding.line and (finding.path, finding.line) in changed_lines:
            comment: dict[str, Any] = {
                "path": finding.path,
                "line": finding.line,
                "side": "RIGHT",
                "body": format_finding_body(finding),
            }
            if (
                finding.start_line
                and finding.start_line != finding.line
                and (finding.path, finding.start_line) in changed_lines
            ):
                comment["start_line"] = finding.start_line
                comment["start_side"] = "RIGHT"
            comments.append(comment)

    summary = build_summary(result, len(comments), blocking)
    review_payload: dict[str, Any] = {"commit_id": commit_id, "body": summary, "event": "COMMENT"}
    if comments:
        review_payload["comments"] = comments

    try:
        github_request(
            "POST",
            f"{api_url}/repos/{repo}/pulls/{pr_number}/reviews",
            token,
            review_payload,
        )
        log(f"Created GitHub PR review with {len(comments)} inline comment(s).")
    except RuntimeError as exc:
        log(str(exc))
        return 1

    blocking_findings = [finding for finding in findings if finding.severity in blocking]
    if blocking_findings:
        log(f"Blocking merge because {len(blocking_findings)} critical/high finding(s) exist.")
        return 1
    log("No blocking findings found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
