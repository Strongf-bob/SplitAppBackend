# Wiki Maintenance

## Source Files

The source of this GitHub Wiki is stored in the backend repository:

- [docs/wiki](https://github.com/Strongf-bob/SplitAppBackend/tree/main/docs/wiki)

The GitHub Wiki itself is a separate git repository:

- `https://github.com/Strongf-bob/SplitAppBackend.wiki.git`

## Automatic Sync

The repository includes a GitHub Actions workflow that synchronizes `docs/wiki/*.md` to the GitHub Wiki.

Sync triggers:

- Push to `main` when Wiki source or core backend contract files change.
- Daily scheduled run.
- Manual `workflow_dispatch`.

Workflow source:

- [.github/workflows/sync-wiki.yml](https://github.com/Strongf-bob/SplitAppBackend/blob/main/.github/workflows/sync-wiki.yml)

## Why Keep Wiki Source In The Repo

GitHub Wiki pages are useful for reading, but they are easy to forget during code changes. Keeping the source in `docs/wiki/` gives the project:

- Normal code review for documentation changes.
- History next to backend code.
- Easy sync from CI.
- A clear reminder to update docs with API, security, or behavior changes.

## How To Update The Wiki

1. Edit the relevant file in `docs/wiki/`.
2. If API behavior changed, update `openapi.yaml` and tests in the same change.
3. Commit with a Conventional Commit message.
4. Push to `main`, or run the `Sync GitHub Wiki` workflow manually.

## Page Naming

Use stable page file names:

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

Internal Wiki links should use GitHub Wiki syntax:

```markdown
[API Reference](API-Reference)
```

