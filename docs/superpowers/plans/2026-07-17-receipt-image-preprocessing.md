# Fast Receipt Image Preprocessing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add CPU-only adaptive receipt-image preprocessing that preserves originals and keeps Splitik to one vision request.

**Architecture:** A focused preprocessing service returns safe metadata and an optional model-ready derivative. Attachment storage keeps the original as source of truth, stores the derivative privately, and selects exactly one private URL for the existing vision request.

**Tech Stack:** Python 3.14, Pillow, FastAPI, Pydantic, MongoDB/S3-compatible storage, Prometheus, pytest.

## Global Constraints

- Do not use a receipt dataset or live model provider for verification.
- Do not add OpenCV, GPU libraries, background workers, or additional AI calls.
- Preserve original attachment bytes.
- Fall back to the original on preprocessing failure.
- Keep storage keys, bytes, and presigned URLs private.
- Keep API behavior, `openapi.yaml`, tests, and docs synchronized.

---

### Task 1: CPU image analysis and derivative generation

**Files:**
- Create: `app/services/receipt_image_preprocessing.py`
- Create: `tests/test_receipt_image_preprocessing.py`
- Modify: `requirements.txt`

**Interfaces:**
- Produces: `preprocess_receipt_image(content: bytes, content_type: str) -> ReceiptImagePreprocessingResult`.
- Result contains `derivative_content`, `derivative_content_type`, and public-safe `metadata`.

- [ ] Write synthetic-image tests for an unchanged normal image, EXIF orientation, proportional resize, low-contrast enhancement, excessive pixel count, malformed content fallback, and safe metadata.
- [ ] Run `python -m pytest tests/test_receipt_image_preprocessing.py -q` and verify RED because the module does not exist.
- [ ] Add a pinned Pillow dependency and implement pixel guards, EXIF transpose, quality signals, adaptive enhancement, bounded encoding, and failure fallback.
- [ ] Run the focused tests and verify GREEN.
- [ ] Run Ruff against the new service and tests.

### Task 2: Private derivative lifecycle and single-URL selection

**Files:**
- Modify: `app/services/splitik_attachments.py`
- Modify: `app/schemas.py`
- Modify: `app/routers/splitik.py`
- Modify: `tests/test_splitik.py`

**Interfaces:**
- Consumes: `preprocess_receipt_image` from Task 1.
- Produces: `delete_attachment(...)`, a `DELETE /api/splitik/attachments/{id}` endpoint, and derivative-aware `image_urls_for_actor(...)`.

- [ ] Add failing tests proving the original object remains byte-identical, derivatives are private, good images use the original, enhanced images use one derivative URL, Mongo fallback remains safe, and delete removes every stored object.
- [ ] Run the focused attachment tests and verify the expected failures.
- [ ] Integrate preprocessing into upload, store safe processing metadata, store private derivative data, select one URL, and implement owner-scoped deletion.
- [ ] Run focused attachment and Splitik vision tests and verify GREEN.
- [ ] Confirm interaction logs still contain neither storage paths nor image URLs.

### Task 3: Metrics, contract, and documentation

**Files:**
- Modify: `app/core/monitoring.py`
- Modify: `docs/wiki/Splitik-Agent.md`
- Modify: `docs/wiki/API-Reference.md`
- Modify: `openapi.yaml`
- Modify: `tests/test_app_config.py`

**Interfaces:**
- Consumes: safe preprocessing outcome, selected variant, and duration from Tasks 1-2.
- Produces: low-cardinality Prometheus preprocessing metrics and synchronized public documentation.

- [ ] Add failing contract tests for processing metadata, attachment deletion, and generated OpenAPI equality.
- [ ] Run the focused contract tests and verify RED.
- [ ] Add preprocessing metrics and document the adaptive single-vision-call behavior and delete endpoint.
- [ ] Regenerate `openapi.yaml` from `app.openapi()`.
- [ ] Run focused tests, `make test`, `make lint`, `make format-check`, OpenAPI equality, and `git diff --check`.
