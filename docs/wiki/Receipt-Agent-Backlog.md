# Receipt Agent Backlog

AI receipt draft parsing имеет серверные text и image flows. Image attachment
проходит CPU-only preprocessing и передается configured vision model через private
presigned URL; результат остается pending draft до human review.

## Текущее Состояние

- Receipt images можно upload, replace, delete и читать через presigned URLs.
- Splitik attachments сохраняют оригинал и создают private model-ready copy только
  для EXIF-поворота, resize, темных или малоконтрастных изображений.
- Image receipt flow делает один vision request; fallback model pool не добавляет
  последовательные вызовы на успешном пути.
- Manual receipt creation, item allocation, confirmation, debt calculation и payment flows реализованы.
- `POST /api/events/{id}/receipt-drafts/ai` вызывает configured LLM models и создает receipt draft из user-provided text.
- AI drafts сохраняются в `receipt_ai_drafts`, требуют human review и не влияют на balances.
- Нативный iOS-клиент может показывать editable review card, disagreement state и model metadata.

## Оставшиеся Provider Decisions

Для дальнейшего усиления image receipt flow еще нужно определить:

- нужен ли PDF contract сверх текущих JPEG/PNG/WebP;
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

- Добавить field-level confidence contract для критичных сумм и позиций.
- Добавить независимую проверку только при low confidence или математическом конфликте.
- Добавить regression tests для malformed vision output, low confidence и provider failures.
- Обновить `openapi.yaml`, API reference и frontend integration docs в том же change set.
