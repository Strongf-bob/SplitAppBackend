# Поддержка Wiki

## Source files

Источник этой GitHub Wiki хранится в backend-репозитории:

- [docs/wiki](https://github.com/Strongf-bob/SplitAppBackend/tree/main/docs/wiki)

Сама GitHub Wiki - отдельный git repository:

- `https://github.com/Strongf-bob/SplitAppBackend.wiki.git`

## Automatic sync

В репозитории есть GitHub Actions workflow, который синхронизирует `docs/wiki/*.md` в GitHub Wiki.

Sync triggers:

- Push в `main`, когда меняются Wiki source или core backend contract files.
- Daily scheduled run.
- Manual `workflow_dispatch`.

Workflow source:

- [.github/workflows/sync-wiki.yml](https://github.com/Strongf-bob/SplitAppBackend/blob/main/.github/workflows/sync-wiki.yml)

## Почему Wiki source лежит в repo

GitHub Wiki удобно читать, но ее легко забыть при изменении кода. Source в `docs/wiki/` дает:

- Normal code review для документации.
- Историю рядом с backend-кодом.
- Автоматическую синхронизацию из CI.
- Явное напоминание обновлять docs вместе с API, security или behavior changes.

## Как обновлять Wiki

1. Изменить нужный файл в `docs/wiki/`.
2. Если изменилось API behavior, обновить `openapi.yaml` и tests в том же изменении.
3. Сделать commit с Conventional Commit message.
4. Push в `main` или manual run workflow `Sync GitHub Wiki`.

## Page naming

Используем стабильные имена файлов:

- `Home.md`
- `Project-Overview.md`
- `Local-Setup.md`
- `API-Reference.md`
- `Domain-Flows.md`
- `iOS-Frontend-Integration.md`
- `Authentication-And-Security.md`
- `Operations-And-Deployment.md`
- `Testing-And-CI.md`
- `Wiki-Maintenance.md`

Internal Wiki links:

```markdown
[API](API-Reference)
```

