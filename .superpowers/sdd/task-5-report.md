# Task 5 report — маршруты онбординга и сопровождение Wiki

## Выполнено

- Создана страница [Онбординг](../../docs/wiki/Onboarding.md) с выбором маршрута по аудитории, общим словарём и ключевыми инвариантами продукта.
- Созданы глубокие технические маршруты [Contributor guide](../../docs/wiki/Contributor-Guide.md) и [Staff engineer guide](../../docs/wiki/Staff-Engineer-Guide.md): локальный baseline, карта слоёв, чтение исходников, security/financial risks, проверки и архитектурные критерии.
- Созданы неинженерные [Executive guide](../../docs/wiki/Executive-Guide.md) и [Product manager guide](../../docs/wiki/Product-Manager-Guide.md): способности продукта, ограничения, данные, риски, планирование и приемка без фрагментов кода.
- Переписана [Поддержка Wiki](../../docs/wiki/Wiki-Maintenance.md): канонический источник `docs/wiki/`, правила frontmatter и links, локальные проверки и публикация в `SplitAppBackend.wiki.git` через `sync-wiki.yml`.

## Фактические основания

Документация ссылается на текущие sources: application wiring и access checks, OpenAPI, Make targets, Docker Compose runtime и workflow синхронизации Wiki. Продуктовые ограничения согласованы с существующими страницами о пользовательском пути, чеках, взаиморасчётах и Splitik.

## Проверки

- Проверены frontmatter, единственный H1 и баланс fenced Markdown blocks в шести изменённых Wiki-страницах.
- Проверено существование всех внутренних Wiki targets: 6 изменённых страниц против 26 доступных Wiki-страниц.
- Проверено отсутствие fenced code/diagram blocks в Executive и Product Manager guides.
- Проверено наличие Mermaid в Onboarding, Contributor, Staff Engineer и Wiki Maintenance guides.
- Выполнен `git diff --check` для изменённой Wiki-документации.

## Границы задачи

- Не менялись backend behavior, OpenAPI, тесты или runtime-конфигурация: задача документирует уже существующее состояние.
- Публикация зеркала GitHub Wiki остаётся задачей workflow после merge/push в `main`; отдельный клон `SplitAppBackend.wiki.git` в этой задаче не изменялся.
