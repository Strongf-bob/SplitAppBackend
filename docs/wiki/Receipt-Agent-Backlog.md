# Receipt Agent Backlog

AI receipt draft parsing уже имеет серверный text flow. OCR/image provider
integration намеренно не реализован, пока не выбран provider contract.

## Текущее Состояние

- Receipt images можно upload, replace, delete и читать через presigned URLs.
- Manual receipt creation, item allocation, confirmation, debt calculation и payment flows реализованы.
- `POST /api/events/{id}/receipt-drafts/ai` вызывает configured LLM models и создает receipt draft из user-provided text.
- AI drafts сохраняются в `receipt_ai_drafts`, требуют human review и не влияют на balances.
- Нативный iOS-клиент может показывать editable review card, disagreement state и model metadata.

## Provider Contract Blockers

OCR/image receipt draft work заблокирован, пока не определены:

- какие image/PDF formats поддерживаются;
- где выполняется OCR и какие данные уходят third-party provider;
- retention policy для provider-side input/output;
- schema confidence thresholds;
- fallback behavior, когда OCR/model disagree;
- redaction rules для private payment/contact данных.

## Safety Rules

- Agent не должен сам создавать confirmed receipt.
- Agent output должен превращаться только в draft payload.
- Backend обязан повторно валидировать payer, participants, items, shares и totals.
- Human review обязателен перед mutation, которая влияет на balances.
- Model metadata и disagreements должны сохраняться для audit/debug.

## Следующие Backend Задачи

- Добавить OCR provider abstraction.
- Добавить file-to-draft endpoint только после privacy/provider decision.
- Добавить regression tests для malformed OCR output, low confidence и provider failures.
- Обновить `openapi.yaml`, API reference и frontend integration docs в том же change set.
