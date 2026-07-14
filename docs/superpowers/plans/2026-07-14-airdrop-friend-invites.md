# AirDrop Friend Invites Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a secure, one-time friend invite that can be shared over AirDrop and explicitly accepted in the iOS app.

**Architecture:** Backend owns hashed, expiring invite records and converts a recipient's explicit acceptance to an accepted friendship. iOS creates a share URL only on user action, persists an unopened custom deep link until login, previews it, and sends the acceptance request from a confirmation sheet.

**Tech Stack:** FastAPI, MongoDB/mongomock, Pydantic, Swift, SwiftUI, UIKit share sheet, XCTest.

## Global Constraints

- Tokens are `secrets.token_urlsafe(32)` values; store only SHA-256 digests.
- Invites expire in 15 minutes, have one accepter, and never silently add a friend.
- An accepted friendship is distinct from event membership and is not created for a blocked pair.
- Use `splitapp://friend-invite/<token>`; do not add universal-link infrastructure in this change.
- Commit every independently verified step.

---

### Task 1: Add backend invite contract and storage indexes

**Files:**
- Modify: `app/schemas.py`, `app/services/indexes.py`, `app/routers/friends.py`, `app/services/__init__.py`, `openapi.yaml`
- Create: `app/services/friend_invites.py`
- Test: `tests/test_services.py`

**Interfaces:**
- `create_friend_invite(db, actor_user_id) -> dict`
- `preview_friend_invite(db, token, actor_user_id) -> dict`
- `accept_friend_invite(db, token, actor_user_id) -> dict`
- `revoke_friend_invite(db, invite_id, actor_user_id) -> None`

- [ ] Write a failing service test that creates an invite, asserts no raw token in `db.friend_invites`, and asserts preview returns the creator but not a token.
- [ ] Run `../SplitAppBackend/.venv/bin/python -m pytest tests/test_services.py -k friend_invite` and confirm failure.
- [ ] Add Pydantic request/response models, hashed invite service, indexes, authenticated routes, service exports, and regenerate OpenAPI.
- [ ] Re-run the focused test and `make lint`; commit `feat(friends): add secure friend invite API`.

### Task 2: Enforce invite lifecycle and friendship invariants

**Files:**
- Modify: `app/services/friend_invites.py`, `tests/test_services.py`, `openapi.yaml`

- [ ] Write failing tests for expiry, self-accept, repeat accept by the same recipient, accept by a second recipient, blocked pair, and sender revoke.
- [ ] Run the focused tests and confirm lifecycle assertions fail before implementation.
- [ ] Atomically consume active tokens, make same-recipient acceptance idempotent, reject disallowed state, and upsert an accepted friendship unless the pair is blocked.
- [ ] Run `make test`, `make lint`, `make format-check`; commit `feat(friends): enforce invite lifecycle`.

### Task 3: Add iOS invite data and deep-link state

**Files:**
- Create: `SplitApp/Domain/Models/FriendInvite.swift`, `SplitApp/Data/DTOs/FriendInviteDTO.swift`, `SplitApp/Data/Network/Endpoints/FriendInviteEndpoints.swift`, `SplitApp/Features/Friends/Model/FriendInviteStore.swift`
- Modify: `SplitApp/Domain/Repositories/FriendsRepositoryContract.swift`, `SplitApp/Data/Repositories/FriendsDataRepository.swift`, `SplitApp/App/SplitAppApp.swift`, `SplitApp/Info.plist`
- Test: `SplitAppTests/FriendInviteStoreTests.swift`, `SplitAppTests/FriendsDataRepositoryTests.swift`

- [ ] Write failing tests for parsing `splitapp://friend-invite/<token>`, rejecting malformed URLs, retaining a token until explicitly cleared, and mapping create/preview/accept endpoints.
- [ ] Run the focused XCTest targets and confirm failure.
- [ ] Add invite domain/DTO/endpoint mapping, repository methods, a `UserDefaults`-backed pending-token store, `splitapp` URL registration, and root URL routing that continues to pass Yandex URLs to its SDK.
- [ ] Run focused XCTest and commit `feat(friends): handle AirDrop invite links`.

### Task 4: Share and accept invites in Friends UI

**Files:**
- Create: `SplitApp/Features/Friends/Views/Components/ShareSheet.swift`, `SplitApp/Features/Friends/Views/Components/FriendInviteAcceptanceSheet.swift`
- Modify: `SplitApp/Features/Friends/ViewModels/FriendsViewModel.swift`, `SplitApp/Features/Friends/Views/FriendsView.swift`, `SplitApp/Features/Friends/Views/Components/FriendsNavigationHeader.swift`
- Test: `SplitAppTests/FriendsViewModelTests.swift`

- [ ] Write a failing view-model test that accepting a preview invokes the repository, clears the pending token, and reloads friendships.
- [ ] Run the focused XCTest target and confirm failure.
- [ ] Add a deliberate AirDrop invite action, present `UIActivityViewController` after invite creation, fetch/preview a pending link, and require explicit accept or decline in a sheet.
- [ ] Run all iOS tests and commit `feat(friends): share and accept AirDrop invites`.

### Task 5: Final verification and integration

**Files:**
- Modify: `docs/wiki/API-Reference.md`, `FRONTEND_BACKEND_TODO.md`

- [ ] Document API lifecycle and mark the AirDrop path delivered.
- [ ] Run backend `make test`, `make lint`, `make format-check`; run iOS `xcodebuild test -project SplitApp.xcodeproj -scheme SplitAppUnitTests -destination 'platform=iOS Simulator,name=iPhone 17,OS=latest'`; run `git diff --check` in both worktrees.
- [ ] Commit documentation in each repository, merge verified feature branches into their `main` branches, re-run respective tests on merged results, and push both `main` branches.
