# Splitik receipt vision design

## Goal

When a user sends one or more images while chatting inside an event, Splitik must treat the message as a request to add a receipt draft and extract the receipt from the image with `minimax-m3` through the existing OpenAI-compatible provider.

## Decision

The backend bypasses the text intent router and text planner for event messages that contain attachments. It reads the authenticated user's private attachment bytes, sends them only in an OpenAI-compatible multimodal `image_url` message to the dedicated `vision` model role, and creates an uncommitted receipt draft. The optional user text is passed as extraction context.

The model receives the image data, but attachment storage keys, bucket names, bytes, and any data URL are never written to interaction logs or returned to the client. All existing ownership and event-access checks remain backend-owned.

## Configuration

`SPLITIK_VISION_MODEL=minimax-m3` is a distinct model role using the same `SPLITIK_LLM_BASE_URL` and `SPLITIK_LLM_API_KEY`. CI/deploy pass this value independently, so deploying text-model changes cannot replace the vision model.

## Verification

Tests prove that an image attachment routes to `vision`, includes a data URL only in the LLM request, preserves private storage metadata, creates a receipt draft rather than a receipt, and does not call the text intent/planner path.
