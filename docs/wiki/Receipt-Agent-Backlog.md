# Receipt Agent Backlog

AI receipt draft parsing has an initial backend-owned text flow. OCR/image
provider integration is intentionally not implemented yet.

## Current Status

- Receipt images can be uploaded, replaced, deleted, and read through presigned URLs.
- Manual receipt creation, item allocation, confirmation, debt calculation, and payment flows are implemented.
- `POST /api/events/{id}/receipt-drafts/ai` calls configured LLM models to
  produce a receipt draft from user-provided text.
- AI drafts are stored in `receipt_ai_drafts`, require human review, and do not
  affect balances or create normal receipts.
- No backend endpoint calls an OCR, bank, or fiscal receipt provider.

## Blocked Boundary

Future OCR/image receipt draft work is blocked until these provider contracts exist:

- OCR/image provider API, authentication, latency limits, and failure modes.
- Image-to-text contract before the existing LLM draft endpoint can consume OCR output.
- Data retention and privacy policy for receipt images, OCR text, and model prompts.
- Confidence scoring and human-review rules before a draft can affect debts.
- Cost/rate-limit controls for provider calls.

## Future Backend Shape

Expected backend-owned boundary:

- `receipt_ai_drafts` collection stores text-based draft metadata, model results, disagreements, status, and reviewer-facing payloads.
- Future image endpoints should create a draft from an uploaded image, read draft state, apply manual corrections, and convert a reviewed draft into a normal receipt.
- Provider calls isolated behind a service interface so OCR/LLM vendors can change without changing the public API.
- Receipt understanding must run primary and verification models from runtime
  config. If they disagree, the backend must escalate to the configured
  escalation model and still return a draft requiring human review.
- Drafts must never affect balances. Only confirmed receipts affect debts.

## Explicit Non-Goals For Now

- No OCR parsing.
- No receipt text extraction.
- No automated payer/share decisions.
- No payment app or bank integration.
