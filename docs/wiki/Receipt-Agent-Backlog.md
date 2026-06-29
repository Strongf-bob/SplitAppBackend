# Receipt Agent Backlog

AI/OCR receipt parsing is intentionally not implemented in the backend yet.

## Current Status

- Receipt images can be uploaded, replaced, deleted, and read through presigned URLs.
- Manual receipt creation, item allocation, confirmation, debt calculation, and payment flows are implemented.
- No backend endpoint calls an OCR, LLM, bank, or fiscal receipt provider.

## Blocked Boundary

Future receipt draft agent work is blocked until these provider contracts exist:

- OCR/image provider API, authentication, latency limits, and failure modes.
- LLM/model contract for turning OCR text into structured receipt draft items.
- Data retention and privacy policy for receipt images, OCR text, and model prompts.
- Confidence scoring and human-review rules before a draft can affect debts.
- Cost/rate-limit controls for provider calls.

## Future Backend Shape

Expected backend-owned boundary:

- `receipt_drafts` collection for extracted draft metadata, raw provider result references, confidence, status, and reviewer metadata.
- Agent endpoints for creating a draft from an uploaded image, reading draft state, applying manual corrections, and converting a reviewed draft into a normal receipt.
- Provider calls isolated behind a service interface so OCR/LLM vendors can change without changing the public API.
- Drafts must never affect balances. Only confirmed receipts affect debts.

## Explicit Non-Goals For Now

- No OCR parsing.
- No AI item classification.
- No receipt text extraction.
- No automated payer/share decisions.
- No payment app or bank integration.
