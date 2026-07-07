# Splitik Planner Design

## Goal

Splitik should understand one user request as a structured backend-validated plan before creating drafts. One request may produce multiple event drafts, multiple receipt drafts for an existing event, or a mixed event-plus-receipt plan that still stays draft-only until explicit confirmation.

## Architecture

The backend remains the source of truth and the only writer. LLM output is treated as untrusted JSON. Splitik asks the LLM for a plan, validates it through typed schemas and allowlists, then creates pending drafts only.

The planner supports these actions:

- `create_event_draft`
- `create_receipt_draft`
- `update_receipt_draft`
- `ask_clarifying_question`

Unsupported actions are rejected before any database write.

## Inputs

`POST /api/splitik/messages` keeps the same public contract: text, mode, entry point, session id, and attachment ids. Backend resolves actor, mode context, session history, active draft scoped to the current event, and sanitized attachment metadata.

All provided attachments are passed to the planner as metadata. If image content or OCR text is not available, the planner must ask for clarification instead of pretending it read the receipt.

## Draft Rules

Receipt drafts are created only for an existing event that the actor can access. Event drafts can be created without committing the event. A request that asks for a new event and receipt together creates an event draft and stores the receipt intent as questions/metadata until the event is confirmed.

Active receipt draft lookup is scoped by actor, session, draft type, and event id. This prevents a follow-up in one event from mutating a draft from another event.

## Guardrails

Planner JSON is validated before writes:

- per-user Splitik message, attachment, draft-count, pending-draft, event-create,
  and receipt-create limits are enforced on the backend;
- action type must be in the allowlist;
- no unknown fields are accepted in planner models;
- `event_id`, `payer_id`, and `share_items.user_id` must belong to visible event members;
- `attachment_ids` must belong to the actor;
- receipt payload must pass `CreateReceiptRequest`;
- unsupported or malformed actions return a clarifying response without draft writes;
- direct money mutation, deletion, payment marking, raw database operations, tool names, and Mongo operators are blocked.

Assistant text is still checked by post-response guardrails before being saved.

## Tests

Regression tests cover multiple event drafts, multiple image attachments passed
into the planner, planner-created receipt drafts from structured text, rejected
unsupported actions, event-scoped active draft updates, and server-enforced
per-user limits.
