# Splitik unified plan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create a single pending event-plus-members-plus-receipts plan and show it in native iOS.

**Architecture:** Backend owns resolution, validation, persistence, and transactional commit. The native app only renders the returned draft and invokes its existing draft commit endpoint.

### Task 1: Backend plan draft

- [ ] Add a failing backend test for a message that returns an event plan with participants and a receipt.
- [ ] Add a plan-draft type, planner action, validation, and atomic commit path.
- [ ] Verify with `make test`, `make lint`, `make format-check`, and OpenAPI generation.

### Task 2: Native iOS draft UI

- [ ] Add failing DTO decoding tests for Splitik drafts.
- [ ] Decode message drafts and add the commit endpoint client.
- [ ] Render a themed SwiftUI plan card with sections and confirmation.
- [ ] Run the iOS unit-test scheme and Simulator build.
