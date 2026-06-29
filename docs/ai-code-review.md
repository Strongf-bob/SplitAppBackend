# AI Code Review

This repository runs Alibaba OpenCodeReview on every pull request through the
`AI Code Review / OpenCodeReview` GitHub Actions job.

## Required Secrets

Configure these repository or organization secrets in GitHub:

- `OCR_LLM_URL` - LLM API endpoint used by OpenCodeReview.
- `OCR_LLM_AUTH_TOKEN` - authentication token for the LLM endpoint.
- `OCR_LLM_MODEL` - model name passed to OpenCodeReview.

The workflow also sets the review language to Russian and asks OpenCodeReview to
write all review comments in Russian.

## Blocking Policy

The publishing script maps findings to these severities:

- `critical` - blocks merge.
- `high` - blocks merge.
- `medium` - comment only.
- `low` - comment only.
- `style` - comment only.

Unknown or missing severities are treated as `medium` so unexpected OCR output is
reported without blocking merges by default.

## Branch Protection

To make AI review required before merge:

1. Open GitHub repository settings.
2. Go to **Rules** > **Rulesets** or **Branches** > **Branch protection rules**.
3. Create or edit the rule for the protected branch, usually `main`.
4. Enable required status checks.
5. Select the `AI Code Review / OpenCodeReview` check.
6. Save the rule.

With this enabled, pull requests with `critical` or `high` OpenCodeReview
findings cannot merge until the finding is fixed or the workflow passes.

## Manual Testing

Open a test pull request that changes backend code. The workflow runs on
`opened`, `synchronize`, `reopened`, and `ready_for_review` pull request events.

To re-run without pushing a new commit, open the pull request checks page in
GitHub Actions and use **Re-run jobs**.

For local parser checks, save a sample OpenCodeReview JSON file and run:

```bash
OCR_OUTPUT_FILE=opencode-review.json \
GITHUB_TOKEN=... \
GITHUB_REPOSITORY=Strongf-bob/SplitAppBackend \
GITHUB_EVENT_PATH=/path/to/pull_request_event.json \
python3 .github/scripts/publish_opencode_review.py
```

The raw OpenCodeReview JSON is uploaded as the `opencode-review-result` artifact
on every workflow run for debugging schema changes.
