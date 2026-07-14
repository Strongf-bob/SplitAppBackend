# Splitik unified creation plan

> Historical design. PWA references are retired as of 2026-07-14; the native iOS application is the only product client.

## Goal

Let one Splitik message describe an event, known users to add, and receipt drafts. Show the complete result only in the native iOS app and commit it only after one explicit confirmation.

## Backend contract

The planner may return `create_event_plan_draft` with an event name, resolved visible-user IDs, and receipt templates. The backend validates every referenced user and persists one pending plan draft; no event, membership, receipt, or balance changes occur at message time. On commit, the backend creates the event, adds participants, resolves receipt shares against the resulting memberships, then creates receipts. If a precondition fails, the plan remains pending and no partial resources are committed.

## Default receipt rules

For text receipt commands, the actor is the payer unless another visible user is explicitly named. Shares are equal over active event participants; when the actor is the only member, the sole share is 1.0. Questions are emitted only for a missing amount, unresolved target event, or ambiguous person reference.

## Native iOS presentation

`SplitikMessageResponse` decodes drafts and questions. SwiftUI renders an interactive unified-plan card, with sections for event, participants, and receipts plus Edit and Confirm actions. It uses the app's `AppTheme` cards and accent colors, not the PWA components.
