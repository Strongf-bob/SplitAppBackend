# AirDrop Friend Invites Design

## Goal

Let an authenticated SplitApp user invite one nearby person to become a confirmed friend by sending a secure link through the iOS system share sheet, including AirDrop.

## User flow

1. The sender opens Friends and chooses "Invite via AirDrop".
2. The app asks the backend for one new invite and presents the system share sheet with its `splitapp://friend-invite/<token>` URL.
3. The recipient opens the URL. If they are not logged in, iOS retains the invite locally until login finishes.
4. The recipient sees the sender's public profile and explicitly accepts or declines.
5. Accepting creates one accepted friendship. It never adds the recipient to an event and never silently creates friendship.

## Security and lifecycle

- A token is generated with `secrets.token_urlsafe(32)` and only its SHA-256 digest is persisted.
- Every token is single-use, bound to one accepting user, and expires after 15 minutes.
- The sender can revoke an active invite. Expired, revoked, or consumed links return a clear non-sensitive error.
- The creator cannot accept their own invite. A friendship blocked by either party cannot be created through an invite.
- Repeating accept from the same recipient is idempotent; any other recipient is rejected after the token has been consumed.
- No raw invite token is logged, stored in Core Data, or returned by preview endpoints.

## Backend API

- `POST /api/friend-invites`: create an invite for the authenticated sender; returns its ID, expiry, sender profile, and share URL.
- `GET /api/friend-invites/{token}/preview`: authenticated recipient obtains a safe preview before deciding.
- `POST /api/friend-invites/{token}/accept`: authenticated recipient consumes the token and returns the accepted friendship.
- `DELETE /api/friend-invites/{id}`: sender revokes an active invite.

`friend_invites` is a separate collection with unique `id` and `token_hash` indexes, plus creator/status and expiry indexes. The API schema and generated OpenAPI document stay in sync.

## iOS architecture

`FriendsRepository` owns invite endpoints and invite DTO/domain mapping. `FriendsViewModel` creates a link on deliberate user action and exposes the share URL. A shared `FriendInviteStore` parses the custom URL at app level, persists a pending token only until resolution, fetches preview after authentication, and drives an acceptance sheet in Friends.

The iOS share sheet is `UIActivityViewController` through a focused SwiftUI wrapper; AirDrop is offered by the operating system alongside other sharing targets. The app declares the `splitapp` URL scheme in `Info.plist`.

## Tests and acceptance criteria

- Backend tests cover hashed-token storage, preview, expiry, self-accept denial, one-recipient consumption, idempotent reaccept, block protection, revoke, and OpenAPI paths.
- iOS tests cover deep-link parsing, repository endpoint mapping, and view-model acceptance/refresh behavior.
- `make test`, `make lint`, `make format-check`, and iOS unit tests pass before merging both branches into `main`.
