# API guide

Практическое руководство для потребителей HTTP API SplitAppBackend. Канонический
машиночитаемый контракт — [`openapi.yaml`](https://github.com/Strongf-bob/SplitAppBackend/blob/main/openapi.yaml); при расхождении с текстом
руководства следует исправить документацию или контракт в том же backend-изменении.

## Базовые правила

- API работает под `/api`; JSON-запросы используют `Content-Type: application/json`.
- Идентификаторы ресурсов передаются как UUID в path.
- Почти все API требуют `Authorization: Bearer <access_token>`. Исключения login и refresh
  определены маршрутом [auth.py](https://github.com/Strongf-bob/SplitAppBackend/blob/main/app/routers/auth.py#L13-L31).
- Сервер извлекает authenticated actor из access token; user ID из payload не даёт права на
  операцию. Проверку Bearer JWT выполняет
  [require_auth_token](https://github.com/Strongf-bob/SplitAppBackend/blob/main/app/dependencies.py#L86-L148).
- Не помещайте access/refresh tokens, presigned URLs, персональные данные или полные ответы API
  в логи, аналитические события и баг-репорты клиента.

## Аутентификация и повтор запроса

1. Передайте Yandex credential только в `POST /api/login`; ответ содержит данные сессии.
2. Храните refresh token только в secure storage платформы.
3. При `401` выполните `POST /api/refresh` один раз, замените tokens и повторите исходный
   запрос. Если refresh не удался, завершите сессию, а не повторяйте запрос бесконечно.
4. `403` означает отсутствие прав или membership — это не временная сетевая ошибка.

## Пагинация

Списки пользователей, событий, чеков, платежей и plans используют offset pagination:

```text
GET /api/events?limit=50&offset=0
```

`limit` задаёт размер страницы (как правило, от 1 до 100), `offset` — число уже пропущенных
результатов. Ответ содержит `items`, `limit`, `offset`, `total`. Увеличивайте offset на число
фактически полученных `items`; `total` — число доступных actor записей до применения страницы.
Не считайте пустой список доказательством отсутствия данных без проверки текущего фильтра и
прав доступа. Примеры серверных ограничений видны в
[users.py](https://github.com/Strongf-bob/SplitAppBackend/blob/main/app/routers/users.py#L10-L72),
[events.py](https://github.com/Strongf-bob/SplitAppBackend/blob/main/app/routers/events.py#L21-L28) и
[receipts.py](https://github.com/Strongf-bob/SplitAppBackend/blob/main/app/routers/receipts.py#L39-L47).

## Ошибки и UX

Обычный ответ ошибки имеет форму:

```json
{ "detail": "..." }
```

| Код | Смысл для клиента | Действие |
| --- | --- | --- |
| `400` | Команда недопустима в текущем доменном состоянии. | Покажите безопасное объяснение и обновите данные при необходимости. |
| `401` | Нет, истёк или неверен access token. | Один refresh/retry либо logout. |
| `403` | Actor не участник или не имеет нужной роли. | Не retry; убрать недоступное действие и обновить экран. |
| `404` | Ресурс недоступен/не найден. | Вернуться к списку или сообщить, что объект больше недоступен. |
| `409` | Конфликт актуального состояния. | Обновить ресурс и предложить пользователю повторить осмысленное действие. |
| `422` | Payload или path/query parameter не прошёл schema validation. | Исправить клиентский payload; не retry без изменения. |
| `429` | Сработал rate limit. | Подождать и ограничить автоматические повторы. |
| `500` | Непредвиденная server failure. | Показать generic error и отправить безопасный diagnostics signal без секретов. |

Не используйте текст `detail` как стабильный программный код. UI должен быть готов к изменению
формулировки и не раскрывать пользователю внутренние детали.

## Идемпотентность

Для финансовых create-команд передавайте непустой заголовок:

```http
Idempotency-Key: <новый UUID для одного намерения пользователя>
```

Он обязателен для создания чека, payment, payment request, settlement plan, выполнения plan и
`mark-paid`. Это видно в исходниках
[receipts.py](https://github.com/Strongf-bob/SplitAppBackend/blob/main/app/routers/receipts.py#L22-L36),
[payments.py](https://github.com/Strongf-bob/SplitAppBackend/blob/main/app/routers/payments.py#L12-L79) и
[events.py](https://github.com/Strongf-bob/SplitAppBackend/blob/main/app/routers/events.py#L181-L235).

Создавайте ключ в момент подтверждения пользователем действия. При timeout или разрыве сети
повторите тот же запрос с тем же ключом; для нового осознанного действия создайте другой ключ.
Не переиспользуйте ключ между разными ресурсами или разными намерениями.

## Деньги и состояние расчётов

- Денежные поля передаются и хранятся как целое число копеек. Не выполняйте расчёты через
  `Float`/`Double`; форматируйте целое значение только на границе UI.
- `GET /api/events/{id}/balances` и settlement preview — серверные вычисления, а не данные,
  которые клиент должен пересчитать из кэша.
- Settlement plan — предложение расчёта. Его одобрение и `execute` создают контролируемые
  payment requests, но сами по себе не подтверждают получение денег.
- `mark-paid` фиксирует заявление плательщика; завершение денежного перехода требует отдельного
  подтверждения получателя через payment flow.
- Закрытое событие запрещает финансовые mutation-команды; перечитайте ресурс после ошибки,
  а не пытайтесь обойти ограничение повтором.

Детальная предметная модель находится в [Деньги и взаиморасчёты](Money-And-Settlement) и
[Domain flows](Domain-Flows).

## Порядок совместимого изменения контракта

Backend и iOS-клиент поставляются независимо, поэтому для каждого изменения соблюдайте порядок:

1. Зафиксируйте новый контракт в schemas, runtime OpenAPI, `openapi.yaml`, тестах и wiki.
2. Сначала разверните backend с обратной совместимостью: добавьте optional поле с default,
   новый endpoint или параллельное поведение; не меняйте существующее значение поля молча.
3. Выпустите iOS-клиент, который умеет читать и старый, и расширенный ответ, а для mutation
   корректно передаёт новые поля/headers.
4. Наблюдайте принятие версии клиента; только затем отдельно объявляйте и удаляйте legacy
   контракт как breaking change.

Перед изменением существующего endpoint дополнительно проверьте: сохранены ли auth и
membership semantics, pagination envelope, integer-kopeck representation, error class и
idempotency requirement. Нельзя заменять эти свойства без явной миграции.

## Related Pages

- [API reference](API-Reference)
- [Интеграция SplitApp и SplitAppBackend](SplitApp-Integration)
- [Аутентификация и безопасность](Authentication-And-Security)
- [Деньги и взаиморасчёты](Money-And-Settlement)
- [Поддержка Wiki](Wiki-Maintenance)
