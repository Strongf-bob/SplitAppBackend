# AI Code Review

В репозитории есть GitHub Actions job `AI Code Review / OpenCodeReview`, который
запускает Alibaba OpenCodeReview на pull request.

Также есть `AI Test Failure Analysis / Analyze Test Failure`: job запускает
`make test`, а при падении отправляет test log и PR diff в тот же LLM endpoint и
публикует diagnostic PR comment. Основным merge-blocking источником правды
остается обычный `Backend CI/CD / Test`.

## Required Secrets

В repository или organization secrets GitHub нужно настроить:

- `OCR_LLM_URL` — LLM API endpoint для OpenCodeReview.
- `OCR_LLM_AUTH_TOKEN` — authentication token для LLM endpoint.
- `OCR_LLM_MODEL` — model name для OpenCodeReview.

Workflow выставляет review language в Russian и просит OpenCodeReview писать
review comments по-русски. Те же secrets используются для AI test failure
analysis.

## Blocking Policy

Publishing script мапит findings в severities:

- `critical` — блокирует merge.
- `high` — блокирует merge.
- `medium` — comment only.
- `low` — comment only.
- `style` — comment only.

Unknown или missing severities считаются `medium`, чтобы неожиданный OCR output
попал в комментарии, но не блокировал merge по умолчанию.

## Branch Protection

Чтобы сделать AI review обязательным перед merge:

1. Откройте GitHub repository settings.
2. Перейдите в **Rules** > **Rulesets** или **Branches** > **Branch protection rules**.
3. Создайте или обновите rule для protected branch, обычно `main`.
4. Включите required status checks.
5. Выберите check `AI Code Review / OpenCodeReview`.
6. Сохраните rule.

После этого PR с `critical` или `high` OpenCodeReview findings нельзя смержить,
пока finding не исправлен или workflow не пройдет.

`AI Test Failure Analysis / Analyze Test Failure` не стоит делать required
blocking check без отдельного решения. Regular test check уже блокирует merge при
падении тестов; AI analysis нужен для объяснения в PR discussion.

## Manual Testing

Откройте test pull request с backend-code изменением. Workflow запускается на
`opened`, `synchronize`, `reopened` и `ready_for_review`.

Для rerun без нового commit используйте **Re-run jobs** на странице checks в
GitHub Actions.

Для локальной проверки parser сохраните sample OpenCodeReview JSON и выполните:

```bash
OCR_OUTPUT_FILE=opencode-review.json \
GITHUB_TOKEN=... \
GITHUB_REPOSITORY=Strongf-bob/SplitAppBackend \
GITHUB_EVENT_PATH=/path/to/pull_request_event.json \
python3 .github/scripts/publish_opencode_review.py
```

Raw OpenCodeReview JSON загружается как artifact `opencode-review-result`.

При падении тестов AI failure workflow загружает artifact
`ai-test-failure-context`:

- `test-output.log` — полный `make test` output.
- `pr-diff.patch` — PR diff, который был передан в LLM context.

Перед отправкой logs и diffs в LLM analyzer редактирует common secret patterns.
Tests все равно не должны печатать secrets, tokens, credentials или private user data.
