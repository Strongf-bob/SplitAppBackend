import importlib
import threading
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from app import schemas
from app.core import tokens
from app.services import (
    audit,
    auth,
    balances,
    client_reports,
    contacts,
    disputes,
    events,
    friends,
    payments,
    receipt_image,
    receipts,
    reports,
    home,
    users,
)
from app.services.idempotency import _request_hash, run_idempotent_create

from tests.conftest import (
    EVENT_ID,
    USER_A,
    USER_B,
    USER_C,
    confirm_receipt_for_all,
    payment_payload,
    receipt_payload,
    seed_event,
)


def assert_status(exc: Exception, status_code: int) -> None:
    assert getattr(exc, "status_code", None) == status_code


def get_settlement_preview(db, event_id: str, actor_user_id: str) -> dict:
    try:
        module = importlib.import_module("app.services.settlements")
    except ModuleNotFoundError:
        pytest.fail("app.services.settlements module is missing")
    return module.get_settlement_preview(db, event_id, actor_user_id)


def settlement_service():
    try:
        return importlib.import_module("app.services.settlements")
    except ModuleNotFoundError:
        pytest.fail("app.services.settlements module is missing")


def add_active_member(db, user_id: str) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    db.event_memberships.insert_one(
        {
            "id": f"aaaaaaaa-0000-0000-0000-{user_id[:12]}",
            "event_id": EVENT_ID,
            "user_id": user_id,
            "role": "member",
            "status": "active",
            "joined_at": now,
            "removed_at": None,
            "created_at": now,
            "updated_at": now,
        }
    )


def create_cycle_settlement_source(db, *, extra_same_edge: bool = False) -> list[dict]:
    seed_event(db)
    add_active_member(db, USER_C)
    first = receipts.create_receipt(
        db,
        EVENT_ID,
        schemas.CreateReceiptRequest(
            payer_id=USER_A,
            title="A paid for B",
            total_amount_kopecks=500,
            items=[
                schemas.CreateReceiptItemRequest(
                    name="AB",
                    cost_kopecks=500,
                    share_items=[schemas.CreateShareItemRequest(user_id=USER_B, share_value="1")],
                )
            ],
        ),
        USER_A,
    )
    created = [first]
    if extra_same_edge:
        created.append(
            receipts.create_receipt(
                db,
                EVENT_ID,
                schemas.CreateReceiptRequest(
                    payer_id=USER_A,
                    title="A paid again for B",
                    total_amount_kopecks=200,
                    items=[
                        schemas.CreateReceiptItemRequest(
                            name="AB again",
                            cost_kopecks=200,
                            share_items=[
                                schemas.CreateShareItemRequest(user_id=USER_B, share_value="1")
                            ],
                        )
                    ],
                ),
                USER_A,
            )
        )
        created.append(
            receipts.create_receipt(
                db,
                EVENT_ID,
                schemas.CreateReceiptRequest(
                    payer_id=USER_C,
                    title="C paid for A",
                    total_amount_kopecks=400,
                    items=[
                        schemas.CreateReceiptItemRequest(
                            name="CA",
                            cost_kopecks=400,
                            share_items=[
                                schemas.CreateShareItemRequest(user_id=USER_A, share_value="1")
                            ],
                        )
                    ],
                ),
                USER_C,
            )
        )
    second = receipts.create_receipt(
        db,
        EVENT_ID,
        schemas.CreateReceiptRequest(
            payer_id=USER_B,
            title="B paid for C",
            total_amount_kopecks=500,
            items=[
                schemas.CreateReceiptItemRequest(
                    name="BC",
                    cost_kopecks=500,
                    share_items=[schemas.CreateShareItemRequest(user_id=USER_C, share_value="1")],
                )
            ],
        ),
        USER_B,
    )
    created.append(second)
    for receipt in created:
        confirm_receipt_for_all(db, receipt["id"], receipt["payer_id"])
    return created


def create_settlement_source_change(db, *, title: str = "Changed source") -> dict:
    receipt = receipts.create_receipt(
        db,
        EVENT_ID,
        schemas.CreateReceiptRequest(
            payer_id=USER_A,
            title=title,
            total_amount_kopecks=100,
            items=[
                schemas.CreateReceiptItemRequest(
                    name=title,
                    cost_kopecks=100,
                    share_items=[schemas.CreateShareItemRequest(user_id=USER_C, share_value="1")],
                )
            ],
        ),
        USER_A,
    )
    confirm_receipt_for_all(db, receipt["id"], USER_A)
    return receipt


def create_approved_settlement_plan(db, *, extra_same_edge: bool = False) -> tuple[object, dict]:
    create_cycle_settlement_source(db, extra_same_edge=extra_same_edge)
    service = settlement_service()
    plan = service.create_settlement_plan(db, EVENT_ID, USER_A, idempotency_key="plan")
    approved = plan
    for user_id in plan["required_approver_ids"]:
        approved = service.approve_settlement_plan(db, plan["id"], user_id)
    assert approved["status"] == "approved"
    return service, approved


def audit_action_count(db, action: str, resource_id: str) -> int:
    return db.audit_events.count_documents({"action": action, "resource_id": resource_id})


def audit_action_total(db, action: str) -> int:
    return db.audit_events.count_documents({"action": action})


def remove_active_member(db, user_id: str) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    db.event_memberships.update_one(
        {"event_id": EVENT_ID, "user_id": user_id},
        {
            "$set": {
                "status": "removed",
                "removed_at": now,
                "updated_at": now,
            }
        },
    )


def test_event_create_and_list_for_actor(db):
    from tests.conftest import seed_users

    seed_users(db)
    created = events.create_event(db, schemas.EventCreate(name=" Weekend "), USER_A)

    assert created["name"] == "Weekend"
    assert created["creator_id"] == USER_A
    assert created["receipt_creation_policy"] == "participants_can_add"
    assert created["participants_invite_policy"] == "creator_only"
    assert [
        (item["user_id"], item["role"], item["status"]) for item in created["participants"]
    ] == [(USER_A, "creator", "active")]
    page = events.list_events(db, USER_A, limit=50, offset=0)

    assert [event["id"] for event in page["items"]] == [created["id"]]
    assert page["total"] == 1


def test_event_create_daily_limit_is_enforced(db, monkeypatch):
    from tests.conftest import seed_users

    monkeypatch.setenv("EVENT_CREATE_DAILY_LIMIT", "1")
    seed_users(db)
    events.create_event(db, schemas.EventCreate(name="First"), USER_A)

    try:
        events.create_event(db, schemas.EventCreate(name="Second"), USER_A)
    except Exception as exc:
        assert_status(exc, 429)
    else:
        raise AssertionError("Expected daily event creation limit to fail")

    assert db.events.count_documents({"creator_id": USER_A}) == 1


def test_event_policies_are_validated_and_enforced(db):
    seed_event(db)

    updated = events.update_event(
        db,
        EVENT_ID,
        schemas.EventUpdate(
            receipt_creation_policy="creator_only",
            receipt_finalization_policy="creator_finalizes",
            participants_invite_policy="participants_can_invite_directly",
        ),
        USER_A,
    )

    assert updated["receipt_creation_policy"] == "creator_only"
    try:
        receipts.create_receipt(db, EVENT_ID, receipt_payload(), USER_B)
    except Exception as exc:
        assert_status(exc, 403)
    else:
        raise AssertionError("Expected creator-only receipt creation to fail for member")

    receipt = receipts.create_receipt(db, EVENT_ID, receipt_payload(), USER_A)
    confirmed, _ = confirm_receipt_for_all(db, receipt["id"])
    invite = events.create_event_invite(
        db, EVENT_ID, schemas.CreateEventInviteRequest(expires_in_seconds=3600), USER_B
    )

    assert confirmed["status"] == "confirmed"
    assert invite["status"] == "active"


def test_event_policy_rejects_invalid_values(db):
    seed_event(db)

    with pytest.raises(ValidationError):
        schemas.EventUpdate(debt_display_mode="bad")


def test_update_current_user_profile(db):
    from tests.conftest import seed_users

    seed_users(db)

    user = users.update_current_user(
        db,
        USER_A,
        schemas.UserUpdate(
            name=" Alice Updated ",
            email=" updated@example.com ",
            avatar_url=" https://cdn.example.com/a.jpg ",
        ),
    )

    assert user["name"] == "Alice Updated"
    assert user["email"] == "updated@example.com"
    assert user["avatar_url"] == "https://cdn.example.com/a.jpg"
    assert db.users.find_one({"id": USER_A})["phone_number"] == "+10000000001"
    assert db.audit_events.find_one({"action": "user.profile_updated", "resource_id": USER_A})


def test_get_current_user_profile_returns_authenticated_actor(db):
    from tests.conftest import seed_users

    seed_users(db)

    user = users.get_current_user(db, USER_A)

    assert user["id"] == USER_A
    assert user["name"] == "Alice"
    assert user["email"] == "alice@example.com"
    assert user["phone_number"] == "+10000000001"


def test_yandex_login_imports_profile_once_and_reuses_stored_fields(db, fake_s3, monkeypatch):
    profile = {
        "id": "yandex-1",
        "login": "alice_login",
        "first_name": "Alice",
        "last_name": "Ivanova",
        "sex": "female",
        "birthday": "1990-01-02",
        "default_email": "alice@example.com",
        "default_avatar_id": "avatar-1",
    }
    monkeypatch.setattr(auth, "_fetch_yandex_profile", lambda _: profile)
    imported_avatar_urls = []

    def import_avatar(_s3, *, user_id, yandex_avatar_url):
        imported_avatar_urls.append((user_id, yandex_avatar_url))
        return f"users/{user_id}/avatar.jpg"

    monkeypatch.setattr(auth, "import_yandex_avatar", import_avatar)

    result = auth.login_with_yandex_oauth(db, "token", s3=fake_s3)
    stored = db.users.find_one({"yandex_id": "yandex-1"})

    assert result["user"]["name"] == "Alice Ivanova"
    assert result["user"]["phone_number"] == "yandex:yandex-1"
    assert result["user"]["first_name"] == "Alice"
    assert result["user"]["last_name"] == "Ivanova"
    assert result["user"]["sex"] == "female"
    assert result["user"]["birthday"] == "1990-01-02"
    assert stored["default_avatar_id"] == "avatar-1"
    assert stored["avatar_key"] == f"users/{stored['id']}/avatar.jpg"
    assert stored["yandex_profile_imported_at"] is not None
    assert result["user"]["avatar_url"] == f"/avatars/{stored['id']}"

    profile["default_phone"] = {"number": "8 (999) 000-00-01"}
    profile["first_name"] = "Changed in Yandex"
    second = auth.login_with_yandex_oauth(db, "token", s3=fake_s3)

    assert db.users.count_documents({"yandex_id": "yandex-1"}) == 1
    assert second["user"]["name"] == "Alice Ivanova"
    assert second["user"]["phone_number"] == "yandex:yandex-1"
    assert len(imported_avatar_urls) == 1


def test_yandex_login_succeeds_when_avatar_import_fails(db, fake_s3, monkeypatch):
    monkeypatch.setattr(auth, "_fetch_yandex_profile", lambda _: {"id": "yandex-1"})
    monkeypatch.setattr(auth, "import_yandex_avatar", lambda *_args, **_kwargs: None)

    result = auth.login_with_yandex_oauth(db, "token", s3=fake_s3)

    stored = db.users.find_one({"yandex_id": "yandex-1"})
    assert result["user"]["avatar_url"] is None
    assert "avatar_key" not in stored
    assert stored["yandex_profile_imported_at"] is not None


def test_update_current_user_discovery_and_payment_hints(db):
    from tests.conftest import seed_users

    seed_users(db)

    user = users.update_current_user(
        db,
        USER_A,
        schemas.UserUpdate(
            public_handle="@Alice_1",
            discovery_enabled=True,
            payment_phone="+79990000000",
            payment_phone_visibility="event_members",
        ),
    )
    stored = db.users.find_one({"id": USER_A})

    assert user["public_handle"] == "alice_1"
    assert user["discovery_enabled"] is True
    assert user["payment_phone"] == "+79990000000"
    assert user["phone_verified"] is False
    assert stored["search_name"] == "alice"


def test_user_search_is_opt_in_and_does_not_search_phone(db):
    from tests.conftest import seed_users

    seed_users(db)
    users.update_current_user(
        db,
        USER_B,
        schemas.UserUpdate(
            public_handle="bob_split",
            discovery_enabled=True,
            payment_phone="+79990000002",
        ),
    )

    by_handle = users.search_users(db, USER_A, "bob", limit=20, offset=0)
    by_phone = users.search_users(db, USER_A, "79990000002", limit=20, offset=0)

    assert [user["id"] for user in by_handle["items"]] == [USER_B]
    assert by_phone["items"] == []


def test_import_contacts_upserts_and_matches_by_normalized_phone(db):
    from tests.conftest import seed_users

    seed_users(db)

    first = contacts.import_user_contacts(
        db,
        USER_A,
        schemas.ContactImportRequest(
            contacts=[
                schemas.ContactImportItem(
                    display_name=" Боб из контактов ",
                    phone_numbers=["+1 (000) 000-0002"],
                ),
                schemas.ContactImportItem(
                    display_name="No Phone",
                    phone_numbers=["not a phone"],
                ),
            ]
        ),
    )
    second = contacts.import_user_contacts(
        db,
        USER_A,
        schemas.ContactImportRequest(
            contacts=[
                schemas.ContactImportItem(
                    display_name="Bob Local",
                    phone_numbers=["+10000000002"],
                )
            ]
        ),
    )
    page = contacts.list_user_contacts(db, USER_A, limit=20, offset=0)

    assert first["imported"] == 1
    assert first["matched"] == 1
    assert first["skipped"] == 1
    assert first["items"][0]["display_name"] == "Боб из контактов"
    assert first["items"][0]["matched_user_id"] == USER_B
    assert first["items"][0]["matched_user"]["name"] == "Bob"
    assert first["items"][0]["matched_user"]["display_name"] == "Боб из контактов"
    assert second["items"][0]["display_name"] == "Bob Local"
    assert db.user_contacts.count_documents({"owner_user_id": USER_A}) == 1
    assert page["total"] == 1


def test_contacts_are_private_to_owner(db):
    from tests.conftest import seed_users

    seed_users(db)
    contacts.import_user_contacts(
        db,
        USER_A,
        schemas.ContactImportRequest(
            contacts=[
                schemas.ContactImportItem(
                    display_name="Bob Local",
                    phone_numbers=["+10000000002"],
                )
            ]
        ),
    )

    assert contacts.list_user_contacts(db, USER_A, limit=20, offset=0)["total"] == 1
    assert contacts.list_user_contacts(db, USER_C, limit=20, offset=0)["items"] == []


def test_sensitive_user_search_is_rate_limited(db, monkeypatch):
    from tests.conftest import seed_users

    monkeypatch.setenv("RATE_LIMIT_MAX_REQUESTS", "1")
    monkeypatch.setenv("RATE_LIMIT_WINDOW_SECONDS", "60")
    seed_users(db)
    users.update_current_user(
        db,
        USER_B,
        schemas.UserUpdate(public_handle="bob_split", discovery_enabled=True),
    )

    users.search_users(db, USER_A, "bob", limit=20, offset=0)
    try:
        users.search_users(db, USER_A, "bob", limit=20, offset=0)
    except Exception as exc:
        assert_status(exc, 429)
    else:
        raise AssertionError("Expected repeated sensitive search to be rate limited")


def test_payment_phone_visibility_respects_event_membership(db):
    seed_event(db)
    users.update_current_user(
        db,
        USER_B,
        schemas.UserUpdate(payment_phone="+79990000002", payment_phone_visibility="event_members"),
    )

    visible = users.list_users(db, USER_A, limit=50, offset=0)
    hidden = users.search_users(db, USER_C, "bob", limit=20, offset=0)

    bob_visible = next(user for user in visible["items"] if user["id"] == USER_B)
    assert bob_visible["payment_phone"] == "+79990000002"
    assert hidden["items"] == []


def test_current_user_financial_stats_counts_events_and_balances(db):
    seed_event(db)
    receipt = receipts.create_receipt(db, EVENT_ID, receipt_payload(), USER_A)
    confirm_receipt_for_all(db, receipt["id"])
    db.events.update_one({"id": EVENT_ID}, {"$set": {"is_closed": True}})

    stats_a = users.get_current_user_financial_stats(db, USER_A)
    stats_b = users.get_current_user_financial_stats(db, USER_B)

    assert stats_a == {
        "open_events_count": 0,
        "closed_events_count": 1,
        "outstanding_owed_kopecks": 0,
        "outstanding_receivable_kopecks": 5000,
    }
    assert stats_b == {
        "open_events_count": 0,
        "closed_events_count": 1,
        "outstanding_owed_kopecks": 5000,
        "outstanding_receivable_kopecks": 0,
    }


def test_friend_request_accept_remove_and_block(db):
    from tests.conftest import seed_users

    seed_users(db)

    request = friends.create_friend_request(db, schemas.FriendRequestCreate(user_id=USER_B), USER_A)
    accepted = friends.accept_friend_request(db, request["id"], USER_B)
    page = friends.list_friendships(db, USER_A, status_filter="accepted", limit=50, offset=0)

    assert request["status"] == "requested"
    assert accepted["status"] == "accepted"
    assert [item["id"] for item in page["items"]] == [request["id"]]
    assert page["items"][0]["peer"]["id"] == USER_B
    assert page["items"][0]["peer"]["name"] == "Bob"

    friends.remove_friendship(db, request["id"], USER_A)
    removed = db.friends.find_one({"id": request["id"]})
    assert removed["status"] == "removed"

    second = friends.create_friend_request(db, schemas.FriendRequestCreate(user_id=USER_B), USER_A)
    blocked = friends.block_friendship(db, second["id"], USER_B)
    assert blocked["status"] == "blocked"
    assert blocked["blocked_by"] == USER_B


def test_friend_request_reject_and_authorization(db):
    from tests.conftest import seed_users

    seed_users(db)
    request = friends.create_friend_request(db, schemas.FriendRequestCreate(user_id=USER_B), USER_A)

    try:
        friends.accept_friend_request(db, request["id"], USER_A)
    except Exception as exc:
        assert_status(exc, 403)
    else:
        raise AssertionError("Expected requester accept to fail")

    rejected = friends.reject_friend_request(db, request["id"], USER_B)

    assert rejected["status"] == "rejected"


def test_friend_invite_stores_only_token_hash_and_previews_sender(db):
    from app.services import friend_invites
    from tests.conftest import seed_users

    seed_users(db)

    created = friend_invites.create_friend_invite(db, USER_A)
    stored = db.friend_invites.find_one({"id": created["id"]})
    preview = friend_invites.preview_friend_invite(db, created["token"], USER_B)

    assert created["invite_url"] == f"splitapp://friend-invite/{created['token']}"
    assert "token" not in stored
    assert stored["token_hash"] != created["token"]
    assert preview["creator"]["id"] == USER_A
    assert "token" not in preview


def test_friend_invite_accepts_once_and_is_idempotent_for_recipient(db):
    from app.services import friend_invites
    from tests.conftest import seed_users

    seed_users(db)
    created = friend_invites.create_friend_invite(db, USER_A)

    accepted = friend_invites.accept_friend_invite(db, created["token"], USER_B)
    repeated = friend_invites.accept_friend_invite(db, created["token"], USER_B)

    assert accepted["status"] == "accepted"
    assert repeated["id"] == accepted["id"]
    assert db.friend_invites.find_one({"id": created["id"]})["accepted_by"] == USER_B

    with pytest.raises(Exception) as second_recipient:
        friend_invites.accept_friend_invite(db, created["token"], USER_C)
    assert_status(second_recipient.value, 409)


def test_friend_invite_claim_prevents_another_recipient_friendship(db):
    from app.services import friend_invites
    from tests.conftest import seed_users

    seed_users(db)
    created = friend_invites.create_friend_invite(db, USER_A)
    friendship_id = "claimed-friendship"
    db.friend_invites.update_one(
        {"id": created["id"]},
        {
            "$set": {
                "status": "accepting",
                "accepted_by": USER_B,
                "friendship_id": friendship_id,
            }
        },
    )

    with pytest.raises(Exception) as other_recipient:
        friend_invites.accept_friend_invite(db, created["token"], USER_C)
    assert_status(other_recipient.value, 409)
    assert db.friends.count_documents({"pair_key": ":".join(sorted([USER_A, USER_C]))}) == 0

    accepted = friend_invites.accept_friend_invite(db, created["token"], USER_B)
    stored_invite = db.friend_invites.find_one({"id": created["id"]})
    assert accepted["id"] == friendship_id
    assert stored_invite["status"] == "accepted"


def test_friend_invite_rejects_expiry_self_accept_block_and_revocation(db):
    from app.services import friend_invites
    from tests.conftest import seed_users

    seed_users(db)
    expired = friend_invites.create_friend_invite(db, USER_A)
    db.friend_invites.update_one(
        {"id": expired["id"]}, {"$set": {"expires_at": datetime(2020, 1, 1)}}
    )
    with pytest.raises(Exception) as expiry:
        friend_invites.preview_friend_invite(db, expired["token"], USER_B)
    assert_status(expiry.value, 410)

    own = friend_invites.create_friend_invite(db, USER_A)
    with pytest.raises(Exception) as self_accept:
        friend_invites.accept_friend_invite(db, own["token"], USER_A)
    assert_status(self_accept.value, 400)

    blocked = friends.create_friend_request(db, schemas.FriendRequestCreate(user_id=USER_B), USER_A)
    friends.block_friendship(db, blocked["id"], USER_B)
    blocked_invite = friend_invites.create_friend_invite(db, USER_A)
    with pytest.raises(Exception) as blocked_accept:
        friend_invites.accept_friend_invite(db, blocked_invite["token"], USER_B)
    assert_status(blocked_accept.value, 403)

    revoked = friend_invites.create_friend_invite(db, USER_A)
    friend_invites.revoke_friend_invite(db, revoked["id"], USER_A)
    with pytest.raises(Exception) as revoked_preview:
        friend_invites.preview_friend_invite(db, revoked["token"], USER_B)
    assert_status(revoked_preview.value, 409)


def test_payment_phone_visibility_respects_friendship(db):
    from tests.conftest import seed_users

    seed_users(db)
    request = friends.create_friend_request(db, schemas.FriendRequestCreate(user_id=USER_B), USER_A)
    friends.accept_friend_request(db, request["id"], USER_B)
    users.update_current_user(
        db,
        USER_B,
        schemas.UserUpdate(
            discovery_enabled=True,
            public_handle="bob_friend",
            payment_phone="+79990000002",
            payment_phone_visibility="friends",
        ),
    )

    result = users.search_users(db, USER_A, "bob", limit=20, offset=0)

    assert result["items"][0]["payment_phone"] == "+79990000002"


def test_list_users_only_returns_visible_users(db):
    from tests.conftest import seed_users

    seed_users(db)
    db.users.insert_one(
        {
            "id": "44444444-4444-4444-4444-444444444444",
            "name": "Hidden",
            "phone_number": "+10000000004",
            "email": "hidden@example.com",
        }
    )
    now = datetime(2026, 1, 1, tzinfo=UTC)
    db.events.insert_one(
        {
            "id": EVENT_ID,
            "creator_id": USER_A,
            "name": "Trip",
            "is_closed": False,
            "created_at": now,
            "updated_at": now,
        }
    )
    db.event_memberships.insert_many(
        [
            {
                "id": "membership-a",
                "event_id": EVENT_ID,
                "user_id": USER_A,
                "role": "creator",
                "status": "active",
                "joined_at": now,
            },
            {
                "id": "membership-b",
                "event_id": EVENT_ID,
                "user_id": USER_B,
                "role": "member",
                "status": "active",
                "joined_at": now,
            },
        ]
    )

    visible_ids = {user["id"] for user in users.list_users(db, USER_A, limit=50, offset=0)["items"]}

    assert visible_ids == {USER_A, USER_B}


def test_list_events_returns_paginated_visible_page(db):
    from tests.conftest import seed_users

    seed_users(db)
    base_time = datetime(2026, 1, 1, tzinfo=UTC)
    event_docs = [
        {
            "id": f"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa{index}",
            "creator_id": USER_A,
            "name": f"Trip {index}",
            "is_closed": False,
            "created_at": base_time + timedelta(days=index),
            "updated_at": base_time + timedelta(days=index),
        }
        for index in range(3)
    ]
    db.events.insert_many(event_docs)
    db.event_memberships.insert_many(
        [
            {
                "id": f"membership-{index}",
                "event_id": event["id"],
                "user_id": USER_A,
                "role": "creator",
                "status": "active",
                "joined_at": event["created_at"],
            }
            for index, event in enumerate(event_docs)
        ]
    )
    db.events.insert_one(
        {
            "id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            "creator_id": USER_C,
            "name": "Hidden",
            "is_closed": False,
            "created_at": base_time + timedelta(days=4),
            "updated_at": base_time + timedelta(days=4),
        }
    )

    page = events.list_events(db, USER_A, limit=2, offset=1)

    assert [event["name"] for event in page["items"]] == ["Trip 1", "Trip 0"]
    assert page == {**page, "limit": 2, "offset": 1, "total": 3}


def test_list_users_returns_paginated_visible_page(db):
    from tests.conftest import seed_users

    seed_users(db)
    db.users.insert_many(
        [
            {
                "id": "44444444-4444-4444-4444-444444444444",
                "name": "Dina",
                "phone_number": "+10000000004",
            },
            {
                "id": "55555555-5555-5555-5555-555555555555",
                "name": "Hidden",
                "phone_number": "+10000000005",
            },
        ]
    )
    now = datetime(2026, 1, 1, tzinfo=UTC)
    db.events.insert_one(
        {
            "id": EVENT_ID,
            "creator_id": USER_A,
            "name": "Trip",
            "is_closed": False,
            "created_at": now,
            "updated_at": now,
        }
    )
    db.event_memberships.insert_many(
        [
            {
                "id": f"membership-visible-{index}",
                "event_id": EVENT_ID,
                "user_id": user_id,
                "role": "creator" if user_id == USER_A else "member",
                "status": "active",
                "joined_at": now,
            }
            for index, user_id in enumerate(
                [USER_A, USER_B, "44444444-4444-4444-4444-444444444444"]
            )
        ]
    )

    page = users.list_users(db, USER_A, limit=2, offset=1)

    assert [user["name"] for user in page["items"]] == ["Bob", "Dina"]
    assert page["limit"] == 2
    assert page["offset"] == 1
    assert page["total"] == 3


def test_receipt_create_validates_total_and_membership(db):
    seed_event(db)

    receipt = receipts.create_receipt(db, EVENT_ID, receipt_payload(), USER_A)

    assert receipt["event_id"] == EVENT_ID
    assert receipt["payer_id"] == USER_A
    assert receipt["status"] == "draft"
    assert receipt["version"] == 1
    assert receipt["total_amount_kopecks"] == 10000
    assert len(receipt["items"]) == 1
    stored = db.receipts.find_one({"id": receipt["id"]})
    assert stored["total_amount_kopecks"] == 10000
    assert isinstance(stored["total_amount_kopecks"], int)

    fetched = receipts.get_receipt(db, receipt["id"], USER_B)
    assert fetched["id"] == receipt["id"]
    assert "share_items" not in fetched


def test_receipt_stores_split_and_fiscal_metadata(db):
    seed_event(db)
    payload = receipt_payload()
    payload.category = "restaurant"
    payload.items[0].split_mode = "selected_equal"
    payload.service_fee_amount_kopecks = 500
    payload.tip_amount_kopecks = 1000
    payload.fiscal_total_amount_kopecks = 11500
    payload.vat_amount_kopecks = 0

    receipt = receipts.create_receipt(db, EVENT_ID, payload, USER_A)

    assert receipt["category"] == "restaurant"
    assert receipt["items"][0]["split_mode"] == "selected_equal"
    assert receipt["service_fee_amount_kopecks"] == 500
    assert receipt["tip_amount_kopecks"] == 1000
    assert receipt["fiscal_total_amount_kopecks"] == 11500
    assert receipt["vat_amount_kopecks"] == 0


def test_event_csv_export_includes_debts_receipts_and_payments(db):
    seed_event(db)
    payload = receipt_payload()
    payload.category = "restaurant"
    receipt = receipts.create_receipt(db, EVENT_ID, payload, USER_A)
    confirm_receipt_for_all(db, receipt["id"])
    payment = payments.create_payment(
        db,
        EVENT_ID,
        schemas.PaymentCreate(sender_id=USER_B, receiver_id=USER_A, amount_kopecks=1000),
        USER_B,
    )
    payments.confirm_payment(db, payment["id"], USER_A)

    csv_body = reports.build_event_csv_export(db, EVENT_ID, USER_A)

    assert (
        "section,id,status,debtor_id,creditor_id,sender_id,receiver_id,amount_kopecks,title,category"
        in csv_body
    )
    assert f"receipt,{receipt['id']},confirmed,,,,,10000,Dinner,restaurant" in csv_body
    assert f"payment,{payment['id']},confirmed,,,{USER_B},{USER_A},1000,," in csv_body
    assert f"debt,,,{USER_B},{USER_A},,,4000,," in csv_body
    assert "restaurant" in reports.list_receipt_categories()


def test_confirmed_receipt_fiscal_metadata_cannot_be_changed(db):
    seed_event(db)
    receipt = receipts.create_receipt(db, EVENT_ID, receipt_payload(), USER_A)
    confirm_receipt_for_all(db, receipt["id"])

    try:
        receipts.update_receipt(
            db,
            receipt["id"],
            schemas.UpdateReceiptRequest(tip_amount_kopecks=500),
            USER_A,
        )
    except Exception as exc:
        assert_status(exc, 409)
    else:
        raise AssertionError("Expected confirmed fiscal metadata update to fail")


def test_receipt_create_is_idempotent_for_same_key_and_payload(db):
    seed_event(db)
    payload = receipt_payload()

    first = receipts.create_receipt(
        db, EVENT_ID, payload, USER_A, idempotency_key="receipt-create-1"
    )
    second = receipts.create_receipt(
        db, EVENT_ID, payload, USER_A, idempotency_key="receipt-create-1"
    )

    assert second == first
    assert db.receipts.count_documents({"event_id": EVENT_ID}) == 1
    assert db.idempotency_keys.count_documents({}) == 1


def test_receipt_create_daily_limit_is_enforced(db, monkeypatch):
    monkeypatch.setenv("RECEIPT_CREATE_DAILY_LIMIT", "1")
    seed_event(db)
    receipts.create_receipt(db, EVENT_ID, receipt_payload(), USER_A)

    try:
        receipts.create_receipt(db, EVENT_ID, receipt_payload(), USER_A)
    except Exception as exc:
        assert_status(exc, 429)
    else:
        raise AssertionError("Expected daily receipt creation limit to fail")

    assert db.receipts.count_documents({"event_id": EVENT_ID}) == 1


def test_receipt_create_rejects_idempotency_key_reuse_with_different_payload(db):
    seed_event(db)
    receipts.create_receipt(
        db, EVENT_ID, receipt_payload(), USER_A, idempotency_key="receipt-create-1"
    )
    changed_payload = receipt_payload()
    changed_payload.title = "Different"

    try:
        receipts.create_receipt(
            db, EVENT_ID, changed_payload, USER_A, idempotency_key="receipt-create-1"
        )
    except Exception as exc:
        assert_status(exc, 409)
    else:
        raise AssertionError("Expected idempotency key reuse with different payload to fail")


def test_receipt_detail_requires_event_membership(db):
    seed_event(db)
    receipt = receipts.create_receipt(db, EVENT_ID, receipt_payload(), USER_A)

    try:
        receipts.get_receipt(db, receipt["id"], USER_C)
    except Exception as exc:
        assert_status(exc, 403)
    else:
        raise AssertionError("Expected non-member receipt detail access to fail")


def test_receipt_create_rejects_non_member_payer(db):
    seed_event(db)
    payload = receipt_payload()
    payload.payer_id = UUID(USER_C)

    try:
        receipts.create_receipt(db, EVENT_ID, payload, USER_A)
    except Exception as exc:
        assert_status(exc, 400)
    else:
        raise AssertionError("Expected non-member payer to fail")


def test_receipt_create_rejects_non_member_share_user(db):
    seed_event(db)
    payload = receipt_payload()
    payload.items[0].share_items = [schemas.CreateShareItemRequest(user_id=USER_C, share_value="1")]

    try:
        receipts.create_receipt(db, EVENT_ID, payload, USER_A)
    except Exception as exc:
        assert_status(exc, 400)
    else:
        raise AssertionError("Expected non-member share user to fail")


def test_receipt_create_rejects_invalid_share_sum(db):
    seed_event(db)
    payload = receipt_payload()
    payload.items[0].share_items = [
        schemas.CreateShareItemRequest(user_id=USER_A, share_value="0.25"),
        schemas.CreateShareItemRequest(user_id=USER_B, share_value="0.25"),
    ]

    try:
        receipts.create_receipt(db, EVENT_ID, payload, USER_A)
    except Exception as exc:
        assert_status(exc, 400)
    else:
        raise AssertionError("Expected invalid share sum to fail")


def test_receipt_create_rejects_total_mismatch(db):
    seed_event(db)
    payload = receipt_payload()
    payload.total_amount_kopecks = 9999

    try:
        receipts.create_receipt(db, EVENT_ID, payload, USER_A)
    except Exception as exc:
        assert_status(exc, 400)
    else:
        raise AssertionError("Expected total mismatch to fail")


def test_list_receipts_returns_paginated_active_page(db):
    seed_event(db)
    base_time = datetime(2026, 1, 1, tzinfo=UTC)
    db.receipts.insert_many(
        [
            {
                "id": f"bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb{index}",
                "event_id": EVENT_ID,
                "payer_id": USER_A,
                "title": f"Receipt {index}",
                "total_amount_kopecks": 1000,
                "created_at": base_time + timedelta(days=index),
                "updated_at": base_time + timedelta(days=index),
                "items": [],
                "share_items": [{"id": f"share-{index}"}],
            }
            for index in range(3)
        ]
    )
    db.receipts.insert_one(
        {
            "id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
            "event_id": EVENT_ID,
            "payer_id": USER_A,
            "title": "Deleted",
            "total_amount_kopecks": 1000,
            "created_at": base_time + timedelta(days=4),
            "updated_at": base_time + timedelta(days=4),
            "items": [],
            "share_items": [],
            "deleted_at": base_time + timedelta(days=5),
        }
    )

    page = receipts.list_receipts_by_event(db, EVENT_ID, USER_A, limit=2, offset=1)

    assert [receipt["title"] for receipt in page["items"]] == ["Receipt 1", "Receipt 0"]
    assert all("share_items" not in receipt for receipt in page["items"])
    assert page["limit"] == 2
    assert page["offset"] == 1
    assert page["total"] == 3


def test_balances_use_kopeck_money_math(db):
    seed_event(db)
    payload = schemas.CreateReceiptRequest(
        payer_id=USER_A,
        title="Small amounts",
        total_amount_kopecks=30,
        items=[
            schemas.CreateReceiptItemRequest(
                name="A",
                cost_kopecks=10,
                share_items=[schemas.CreateShareItemRequest(user_id=USER_B, share_value="1")],
            ),
            schemas.CreateReceiptItemRequest(
                name="B",
                cost_kopecks=20,
                share_items=[schemas.CreateShareItemRequest(user_id=USER_B, share_value="1")],
            ),
        ],
    )
    receipt = receipts.create_receipt(db, EVENT_ID, payload, USER_A)

    assert balances.get_event_balances(db, EVENT_ID, USER_A) == []
    confirm_receipt_for_all(db, receipt["id"])

    rows = balances.get_event_balances(db, EVENT_ID, USER_A)

    assert rows == [
        {
            "event_id": EVENT_ID,
            "debitor_id": USER_B,
            "creditor_id": USER_A,
            "amount_kopecks": 30,
        }
    ]


def test_event_raw_balances_preserve_pairwise_edges_while_event_balances_are_globally_simplified(
    db,
):
    seed_event(db)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    db.event_memberships.insert_one(
        {
            "id": "aaaaaaaa-0000-0000-0000-000000000003",
            "event_id": EVENT_ID,
            "user_id": USER_C,
            "role": "member",
            "status": "active",
            "joined_at": now,
            "removed_at": None,
            "created_at": now,
            "updated_at": now,
        }
    )
    first = receipts.create_receipt(
        db,
        EVENT_ID,
        schemas.CreateReceiptRequest(
            payer_id=USER_A,
            title="A paid for B",
            total_amount_kopecks=500,
            items=[
                schemas.CreateReceiptItemRequest(
                    name="AB",
                    cost_kopecks=500,
                    share_items=[schemas.CreateShareItemRequest(user_id=USER_B, share_value="1")],
                )
            ],
        ),
        USER_A,
    )
    second = receipts.create_receipt(
        db,
        EVENT_ID,
        schemas.CreateReceiptRequest(
            payer_id=USER_B,
            title="B paid for C",
            total_amount_kopecks=500,
            items=[
                schemas.CreateReceiptItemRequest(
                    name="BC",
                    cost_kopecks=500,
                    share_items=[schemas.CreateShareItemRequest(user_id=USER_C, share_value="1")],
                )
            ],
        ),
        USER_B,
    )
    confirm_receipt_for_all(db, first["id"], USER_A)
    confirm_receipt_for_all(db, second["id"], USER_B)

    raw_rows = balances.get_event_raw_balances(db, EVENT_ID, USER_A)
    simplified_rows = balances.get_event_balances(db, EVENT_ID, USER_A)

    assert raw_rows == [
        {
            "event_id": EVENT_ID,
            "debitor_id": USER_B,
            "creditor_id": USER_A,
            "amount_kopecks": 500,
        },
        {
            "event_id": EVENT_ID,
            "debitor_id": USER_C,
            "creditor_id": USER_B,
            "amount_kopecks": 500,
        },
    ]
    assert simplified_rows == [
        {
            "event_id": EVENT_ID,
            "debitor_id": USER_C,
            "creditor_id": USER_A,
            "amount_kopecks": 500,
        }
    ]


def test_receipt_validation_creates_reviews_and_blocks_silent_confirmation(db):
    seed_event(db)
    receipt = receipts.create_receipt(db, EVENT_ID, receipt_payload(), USER_A)

    try:
        receipts.confirm_receipt(db, receipt["id"], USER_A)
    except Exception as exc:
        assert_status(exc, 409)
    else:
        raise AssertionError("Expected direct receipt confirmation to fail")

    validated = receipts.validate_receipt(db, receipt["id"], USER_A)
    reviews = receipts.list_receipt_share_reviews(db, receipt["id"], USER_A, limit=50, offset=0)[
        "items"
    ]

    assert validated["status"] == "pending_confirmation"
    assert validated["review_window_expires_at"] is not None
    assert {review["user_id"] for review in reviews} == {USER_A, USER_B}
    assert {review["status"] for review in reviews} == {"pending"}
    assert balances.get_event_balances(db, EVENT_ID, USER_A) == []

    receipts.accept_receipt_share_review(db, receipt["id"], USER_A)
    try:
        receipts.confirm_receipt(db, receipt["id"], USER_A)
    except Exception as exc:
        assert_status(exc, 409)
    else:
        raise AssertionError("Expected missing participant review to block confirmation")


def test_receipt_review_dispute_blocks_until_accepted(db):
    seed_event(db)
    receipt = receipts.create_receipt(db, EVENT_ID, receipt_payload(), USER_A)
    receipts.validate_receipt(db, receipt["id"], USER_A)

    disputed = receipts.dispute_receipt_share_review(
        db,
        receipt["id"],
        schemas.ReceiptShareReviewDispute(reason="Wrong participant"),
        USER_B,
    )

    assert disputed["status"] == "disputed"
    assert receipts.get_receipt(db, receipt["id"], USER_A)["status"] == "disputed"
    try:
        receipts.confirm_receipt(db, receipt["id"], USER_A)
    except Exception as exc:
        assert_status(exc, 409)
    else:
        raise AssertionError("Expected disputed review to block confirmation")

    receipts.accept_receipt_share_review(db, receipt["id"], USER_A)
    receipts.accept_receipt_share_review(db, receipt["id"], USER_B)
    confirmed = receipts.confirm_receipt(db, receipt["id"], USER_A)

    assert confirmed["status"] == "confirmed"


def test_event_review_timeout_never_auto_confirms_receipt(db):
    seed_event(db)
    events.update_event(db, EVENT_ID, schemas.EventUpdate(review_window_seconds=300), USER_A)
    receipt = receipts.create_receipt(db, EVENT_ID, receipt_payload(), USER_A)
    validated = receipts.validate_receipt(db, receipt["id"], USER_A)
    db.receipts.update_one(
        {"id": receipt["id"]},
        {"$set": {"review_window_expires_at": datetime(2025, 1, 1, tzinfo=UTC)}},
    )

    try:
        receipts.confirm_receipt(db, receipt["id"], USER_A)
    except Exception as exc:
        assert_status(exc, 409)
    else:
        raise AssertionError("Expected expired pending reviews to avoid auto-confirmation")

    assert validated["status"] == "pending_confirmation"
    assert balances.get_event_balances(db, EVENT_ID, USER_A) == []


def test_balance_explanations_include_receipts_and_confirmed_payments(db):
    seed_event(db)
    receipt = receipts.create_receipt(db, EVENT_ID, receipt_payload(), USER_A)
    confirm_receipt_for_all(db, receipt["id"])
    payment = payments.create_payment(
        db,
        EVENT_ID,
        schemas.PaymentCreate(sender_id=USER_B, receiver_id=USER_A, amount_kopecks=2000),
        USER_B,
    )
    payments.update_payment(db, payment["id"], schemas.PaymentUpdate(confirmed=True), USER_A)

    rows = balances.get_event_balance_explanations(db, EVENT_ID, USER_A)

    assert rows[0]["debitor_id"] == USER_B
    assert rows[0]["creditor_id"] == USER_A
    assert rows[0]["amount_kopecks"] == 3000
    assert [(item["source_type"], item["amount_kopecks"]) for item in rows[0]["contributions"]] == [
        ("receipt", 5000),
        ("payment", 2000),
    ]


def test_confirmed_payment_on_simplified_edge_reduces_global_net_positions(db):
    seed_event(db)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    db.event_memberships.insert_one(
        {
            "id": "aaaaaaaa-0000-0000-0000-000000000003",
            "event_id": EVENT_ID,
            "user_id": USER_C,
            "role": "member",
            "status": "active",
            "joined_at": now,
            "removed_at": None,
            "created_at": now,
            "updated_at": now,
        }
    )
    first = receipts.create_receipt(
        db,
        EVENT_ID,
        schemas.CreateReceiptRequest(
            payer_id=USER_A,
            title="A paid for B",
            total_amount_kopecks=500,
            items=[
                schemas.CreateReceiptItemRequest(
                    name="AB",
                    cost_kopecks=500,
                    share_items=[schemas.CreateShareItemRequest(user_id=USER_B, share_value="1")],
                )
            ],
        ),
        USER_A,
    )
    second = receipts.create_receipt(
        db,
        EVENT_ID,
        schemas.CreateReceiptRequest(
            payer_id=USER_B,
            title="B paid for C",
            total_amount_kopecks=500,
            items=[
                schemas.CreateReceiptItemRequest(
                    name="BC",
                    cost_kopecks=500,
                    share_items=[schemas.CreateShareItemRequest(user_id=USER_C, share_value="1")],
                )
            ],
        ),
        USER_B,
    )
    confirm_receipt_for_all(db, first["id"], USER_A)
    confirm_receipt_for_all(db, second["id"], USER_B)

    before_payment = balances.get_event_balances(db, EVENT_ID, USER_A)
    payment = payments.create_payment(
        db,
        EVENT_ID,
        schemas.PaymentCreate(sender_id=USER_C, receiver_id=USER_A, amount_kopecks=200),
        USER_C,
    )
    payments.confirm_payment(db, payment["id"], USER_A)
    after_payment = balances.get_event_balances(db, EVENT_ID, USER_A)

    assert before_payment == [
        {
            "event_id": EVENT_ID,
            "debitor_id": USER_C,
            "creditor_id": USER_A,
            "amount_kopecks": 500,
        }
    ]
    assert after_payment == [
        {
            "event_id": EVENT_ID,
            "debitor_id": USER_C,
            "creditor_id": USER_A,
            "amount_kopecks": 300,
        }
    ]


def test_settlement_preview_requires_event_membership(db):
    seed_event(db)

    try:
        get_settlement_preview(db, EVENT_ID, USER_C)
    except Exception as exc:
        assert_status(exc, 403)
    else:
        raise AssertionError("Expected non-member settlement preview to fail")


def test_balance_explain_requires_event_membership(db):
    seed_event(db)

    try:
        balances.get_event_balance_explanations(db, EVENT_ID, USER_C)
    except Exception as exc:
        assert_status(exc, 403)
    else:
        raise AssertionError("Expected non-member balance explain to fail")


def test_settlement_preview_allows_closed_event_and_explains_cycle_compression(db):
    seed_event(db)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    db.event_memberships.insert_one(
        {
            "id": "aaaaaaaa-0000-0000-0000-000000000003",
            "event_id": EVENT_ID,
            "user_id": USER_C,
            "role": "member",
            "status": "active",
            "joined_at": now,
            "removed_at": None,
            "created_at": now,
            "updated_at": now,
        }
    )

    first = receipts.create_receipt(
        db,
        EVENT_ID,
        schemas.CreateReceiptRequest(
            payer_id=USER_A,
            title="A paid for B",
            total_amount_kopecks=500,
            items=[
                schemas.CreateReceiptItemRequest(
                    name="AB",
                    cost_kopecks=500,
                    share_items=[schemas.CreateShareItemRequest(user_id=USER_B, share_value="1")],
                )
            ],
        ),
        USER_A,
    )
    second = receipts.create_receipt(
        db,
        EVENT_ID,
        schemas.CreateReceiptRequest(
            payer_id=USER_B,
            title="B paid for C",
            total_amount_kopecks=500,
            items=[
                schemas.CreateReceiptItemRequest(
                    name="BC",
                    cost_kopecks=500,
                    share_items=[schemas.CreateShareItemRequest(user_id=USER_C, share_value="1")],
                )
            ],
        ),
        USER_B,
    )
    ignored_receipt = receipts.create_receipt(
        db,
        EVENT_ID,
        schemas.CreateReceiptRequest(
            payer_id=USER_A,
            title="Pending",
            total_amount_kopecks=700,
            items=[
                schemas.CreateReceiptItemRequest(
                    name="Ignored",
                    cost_kopecks=700,
                    share_items=[schemas.CreateShareItemRequest(user_id=USER_C, share_value="1")],
                )
            ],
        ),
        USER_A,
    )
    ignored_payment = payments.create_payment(
        db,
        EVENT_ID,
        schemas.PaymentCreate(sender_id=USER_C, receiver_id=USER_A, amount_kopecks=150),
        USER_C,
    )
    confirm_receipt_for_all(db, first["id"], USER_A)
    confirm_receipt_for_all(db, second["id"], USER_B)
    db.events.update_one({"id": EVENT_ID}, {"$set": {"is_closed": True}})

    preview = get_settlement_preview(db, EVENT_ID, USER_A)

    assert preview["event_id"] == EVENT_ID
    assert preview["source_participant_ids"] == [USER_A, USER_B, USER_C]
    assert preview["original_transfer_count"] == 2
    assert preview["recommended_transfer_count"] == 1
    assert preview["original_gross_kopecks"] == 1000
    assert preview["recommended_total_kopecks"] == 500
    assert preview["transfer_count_reduced"] is True
    assert preview["net_positions"] == [
        {"user_id": USER_C, "direction": "owes", "amount_kopecks": 500},
        {"user_id": USER_A, "direction": "receives", "amount_kopecks": 500},
    ]
    assert [
        (row["debitor_id"], row["creditor_id"], row["amount_kopecks"])
        for row in preview["raw_debts"]
    ] == [
        (USER_B, USER_A, 500),
        (USER_C, USER_B, 500),
    ]
    assert preview["raw_debts"][0]["contributions"] == [
        {
            "source_type": "receipt",
            "source_id": first["id"],
            "debitor_id": USER_B,
            "creditor_id": USER_A,
            "amount_kopecks": 500,
            "description": "AB",
        }
    ]
    assert preview["recommended_transfers"] == [
        {"debtor_id": USER_C, "creditor_id": USER_A, "amount_kopecks": 500}
    ]
    assert db.receipts.find_one({"id": ignored_receipt["id"]})["status"] == "draft"
    assert db.payments.find_one({"id": ignored_payment["id"]}).get("confirmed") is False


def test_settlement_preview_handles_empty_and_already_simple_events(db):
    seed_event(db)

    empty_preview = get_settlement_preview(db, EVENT_ID, USER_A)

    assert empty_preview == {
        "event_id": EVENT_ID,
        "raw_debts": [],
        "net_positions": [],
        "recommended_transfers": [],
        "source_participant_ids": [],
        "original_transfer_count": 0,
        "recommended_transfer_count": 0,
        "original_gross_kopecks": 0,
        "recommended_total_kopecks": 0,
        "transfer_count_reduced": False,
    }

    receipt = receipts.create_receipt(db, EVENT_ID, receipt_payload(), USER_A)
    confirm_receipt_for_all(db, receipt["id"])

    simple_preview = get_settlement_preview(db, EVENT_ID, USER_A)

    assert simple_preview["raw_debts"] == [
        {
            "event_id": EVENT_ID,
            "debitor_id": USER_B,
            "creditor_id": USER_A,
            "amount_kopecks": 5000,
            "contributions": [
                {
                    "source_type": "receipt",
                    "source_id": receipt["id"],
                    "debitor_id": USER_B,
                    "creditor_id": USER_A,
                    "amount_kopecks": 5000,
                    "description": "Meal",
                }
            ],
        }
    ]
    assert simple_preview["net_positions"] == [
        {"user_id": USER_B, "direction": "owes", "amount_kopecks": 5000},
        {"user_id": USER_A, "direction": "receives", "amount_kopecks": 5000},
    ]
    assert simple_preview["recommended_transfers"] == [
        {"debtor_id": USER_B, "creditor_id": USER_A, "amount_kopecks": 5000}
    ]
    assert simple_preview["source_participant_ids"] == [USER_A, USER_B]
    assert simple_preview["original_transfer_count"] == 1
    assert simple_preview["recommended_transfer_count"] == 1
    assert simple_preview["original_gross_kopecks"] == 5000
    assert simple_preview["recommended_total_kopecks"] == 5000
    assert simple_preview["transfer_count_reduced"] is False


def test_settlement_plan_create_persists_canonical_snapshot_and_hides_internal_hash(db):
    create_cycle_settlement_source(db, extra_same_edge=True)
    service = settlement_service()

    plan = service.create_settlement_plan(db, EVENT_ID, USER_C, idempotency_key="settlement-plan-1")
    replay = service.create_settlement_plan(
        db, EVENT_ID, USER_C, idempotency_key="settlement-plan-1"
    )

    assert replay == plan
    assert plan["event_id"] == EVENT_ID
    assert plan["status"] == "pending"
    assert plan["algorithm_version"] == "greedy-net-v1"
    assert plan["created_by"] == USER_C
    assert plan["required_approver_ids"] == [USER_A, USER_B, USER_C]
    assert plan["approvals"] == []
    assert plan["preview"]["transfer_count_reduced"] is True
    assert plan["preview"]["original_transfer_count"] == 3
    assert plan["preview"]["recommended_transfer_count"] == 2
    assert "snapshot_hash" not in plan
    assert "canonical_snapshot" not in plan

    ttl = plan["expires_at"] - plan["created_at"]
    assert ttl == timedelta(hours=24)

    stored = db.settlement_plans.find_one({"id": plan["id"]})
    assert stored["snapshot_hash"]
    assert stored["active_key"] == f"{EVENT_ID}:{stored['snapshot_hash']}"
    canonical = stored["canonical_snapshot"]
    assert canonical["algorithm_version"] == "greedy-net-v1"
    assert canonical["active_membership_user_ids"] == [USER_A, USER_B, USER_C]
    raw_edge_with_two_sources = next(
        row for row in canonical["raw_debts"] if row["debitor_id"] == USER_B
    )
    source_ids = [item["source_id"] for item in raw_edge_with_two_sources["contributions"]]
    assert source_ids == sorted(source_ids)


def test_settlement_plan_create_rejects_closed_or_unreduced_preview(db):
    service = settlement_service()
    seed_event(db)
    receipt = receipts.create_receipt(db, EVENT_ID, receipt_payload(), USER_A)
    confirm_receipt_for_all(db, receipt["id"])

    try:
        service.create_settlement_plan(db, EVENT_ID, USER_A, idempotency_key="simple")
    except Exception as exc:
        assert_status(exc, 409)
    else:
        raise AssertionError("Expected unreduced settlement preview to block plan creation")

    db.receipts.delete_many({})
    db.receipt_items.delete_many({})
    db.receipt_share_items.delete_many({})
    db.receipt_share_reviews.delete_many({})
    create_cycle_settlement_source(db)
    db.events.update_one({"id": EVENT_ID}, {"$set": {"is_closed": True}})

    try:
        service.create_settlement_plan(db, EVENT_ID, USER_A, idempotency_key="closed")
    except Exception as exc:
        assert_status(exc, 409)
    else:
        raise AssertionError("Expected closed event to block plan creation")


def test_settlement_plan_duplicate_active_guard_releases_after_rejection(db):
    create_cycle_settlement_source(db)
    service = settlement_service()

    first = service.create_settlement_plan(db, EVENT_ID, USER_A, idempotency_key="plan-a")
    try:
        service.create_settlement_plan(db, EVENT_ID, USER_B, idempotency_key="plan-b")
    except Exception as exc:
        assert_status(exc, 409)
    else:
        raise AssertionError("Expected duplicate active settlement plan to fail")

    rejected = service.reject_settlement_plan(db, first["id"], USER_B, "Need to fix receipt")
    assert rejected["status"] == "rejected"
    assert rejected["rejected_by"] == USER_B
    assert rejected["rejection_reason"] == "Need to fix receipt"
    assert db.settlement_plans.find_one({"id": first["id"]}).get("active_key") is None

    recreated = service.create_settlement_plan(db, EVENT_ID, USER_B, idempotency_key="plan-c")
    assert recreated["id"] != first["id"]
    assert recreated["status"] == "pending"


def test_settlement_plan_create_records_audit_and_domain_once(db, monkeypatch):
    create_cycle_settlement_source(db)
    service = settlement_service()
    domain_events = []
    monkeypatch.setattr(
        service,
        "record_domain_event",
        lambda domain, action: domain_events.append((domain, action)),
    )

    plan = service.create_settlement_plan(db, EVENT_ID, USER_A, idempotency_key="plan")
    replay = service.create_settlement_plan(db, EVENT_ID, USER_A, idempotency_key="plan")

    assert replay == plan
    assert audit_action_count(db, "settlement_plan.created", plan["id"]) == 1
    assert domain_events == [("settlement_plans", "created")]


def test_settlement_plan_approval_requires_source_participant_and_is_idempotent_until_all_approve(
    db,
):
    create_cycle_settlement_source(db)
    user_d = "44444444-4444-4444-4444-444444444444"
    db.users.insert_one(
        {
            "id": user_d,
            "name": "Dana",
            "phone_number": "+10000000004",
            "created_at": datetime(2026, 1, 1, tzinfo=UTC),
            "updated_at": datetime(2026, 1, 1, tzinfo=UTC),
        }
    )
    add_active_member(db, user_d)
    service = settlement_service()
    plan = service.create_settlement_plan(db, EVENT_ID, USER_A, idempotency_key="plan")

    try:
        service.approve_settlement_plan(db, plan["id"], user_d)
    except Exception as exc:
        assert_status(exc, 403)
    else:
        raise AssertionError("Expected non-source event member approval to fail")

    first = service.approve_settlement_plan(db, plan["id"], USER_A)
    repeated = service.approve_settlement_plan(db, plan["id"], USER_A)
    second = service.approve_settlement_plan(db, plan["id"], USER_B)
    final = service.approve_settlement_plan(db, plan["id"], USER_C)

    assert first["status"] == "pending"
    assert repeated == first
    assert second["status"] == "pending"
    assert final["status"] == "approved"
    assert [approval["user_id"] for approval in final["approvals"]] == [USER_A, USER_B, USER_C]
    assert db.settlement_plans.find_one({"id": plan["id"]})["active_key"]


def test_settlement_plan_interleaved_distinct_approvals_are_not_lost(db, monkeypatch):
    create_cycle_settlement_source(db)
    service = settlement_service()
    plan = service.create_settlement_plan(db, EVENT_ID, USER_A, idempotency_key="plan")
    original_get_plan = service._get_plan_or_404
    barrier = threading.Barrier(2)
    lock = threading.Lock()
    blocked_reads = 0

    def interleaved_get_plan(db_arg, plan_id):
        nonlocal blocked_reads
        loaded = original_get_plan(db_arg, plan_id)
        with lock:
            should_block = loaded["id"] == plan["id"] and loaded["status"] == "pending"
            should_block = should_block and blocked_reads < 2
            if should_block:
                blocked_reads += 1
        if should_block:
            barrier.wait(timeout=5)
        return loaded

    monkeypatch.setattr(service, "_get_plan_or_404", interleaved_get_plan)
    errors = []

    def approve(user_id: str) -> None:
        try:
            service.approve_settlement_plan(db, plan["id"], user_id)
        except Exception as exc:  # pragma: no cover - surfaced by assertion below
            errors.append(exc)

    first = threading.Thread(target=approve, args=(USER_A,), name="approve-a")
    second = threading.Thread(target=approve, args=(USER_B,), name="approve-b")
    first.start()
    second.start()
    first.join(timeout=5)
    second.join(timeout=5)

    assert errors == []
    stored = db.settlement_plans.find_one({"id": plan["id"]})
    assert sorted(approval["user_id"] for approval in stored["approvals"]) == [USER_A, USER_B]

    final = service.approve_settlement_plan(db, plan["id"], USER_C)
    assert final["status"] == "approved"
    assert [approval["user_id"] for approval in final["approvals"]] == [USER_A, USER_B, USER_C]


def test_settlement_plan_approvals_record_audit_and_domain_once_per_new_mutation(db, monkeypatch):
    create_cycle_settlement_source(db)
    service = settlement_service()
    domain_events = []
    monkeypatch.setattr(
        service,
        "record_domain_event",
        lambda domain, action: domain_events.append((domain, action)),
    )
    plan = service.create_settlement_plan(db, EVENT_ID, USER_A, idempotency_key="plan")

    service.approve_settlement_plan(db, plan["id"], USER_A)
    service.approve_settlement_plan(db, plan["id"], USER_A)
    service.approve_settlement_plan(db, plan["id"], USER_B)
    approved = service.approve_settlement_plan(db, plan["id"], USER_C)

    assert approved["status"] == "approved"
    assert audit_action_count(db, "settlement_plan.approval_created", plan["id"]) == 3
    assert audit_action_count(db, "settlement_plan.approved", plan["id"]) == 1
    assert domain_events.count(("settlement_plans", "approval_created")) == 3
    assert domain_events.count(("settlement_plans", "approved")) == 1


def test_settlement_plan_source_mismatch_marks_stale_and_blocks_approval(db):
    create_cycle_settlement_source(db)
    service = settlement_service()
    plan = service.create_settlement_plan(db, EVENT_ID, USER_A, idempotency_key="plan")

    new_receipt = receipts.create_receipt(
        db,
        EVENT_ID,
        schemas.CreateReceiptRequest(
            payer_id=USER_A,
            title="Changed source",
            total_amount_kopecks=100,
            items=[
                schemas.CreateReceiptItemRequest(
                    name="Changed",
                    cost_kopecks=100,
                    share_items=[schemas.CreateShareItemRequest(user_id=USER_C, share_value="1")],
                )
            ],
        ),
        USER_A,
    )
    confirm_receipt_for_all(db, new_receipt["id"], USER_A)

    try:
        service.approve_settlement_plan(db, plan["id"], USER_A)
    except Exception as exc:
        assert_status(exc, 409)
    else:
        raise AssertionError("Expected stale settlement plan approval to fail")

    stored = db.settlement_plans.find_one({"id": plan["id"]})
    assert stored["status"] == "stale"
    assert stored.get("active_key") is None


def test_settlement_plan_stale_transition_records_audit_and_domain_once(db, monkeypatch):
    create_cycle_settlement_source(db)
    service = settlement_service()
    domain_events = []
    monkeypatch.setattr(
        service,
        "record_domain_event",
        lambda domain, action: domain_events.append((domain, action)),
    )
    plan = service.create_settlement_plan(db, EVENT_ID, USER_A, idempotency_key="plan")
    create_settlement_source_change(db)

    for _ in range(2):
        try:
            service.approve_settlement_plan(db, plan["id"], USER_A)
        except Exception as exc:
            assert_status(exc, 409)
        else:
            raise AssertionError("Expected stale settlement plan approval to fail")

    assert audit_action_count(db, "settlement_plan.stale", plan["id"]) == 1
    assert domain_events.count(("settlement_plans", "stale")) == 1


def test_settlement_plan_stale_detection_runs_before_old_approver_check(db):
    create_cycle_settlement_source(db)
    service = settlement_service()
    plan = service.create_settlement_plan(db, EVENT_ID, USER_A, idempotency_key="plan")
    user_d = "44444444-4444-4444-4444-444444444444"
    db.users.insert_one(
        {
            "id": user_d,
            "name": "Dana",
            "phone_number": "+10000000004",
            "created_at": datetime(2026, 1, 1, tzinfo=UTC),
            "updated_at": datetime(2026, 1, 1, tzinfo=UTC),
        }
    )
    add_active_member(db, user_d)

    try:
        service.approve_settlement_plan(db, plan["id"], user_d)
    except Exception as exc:
        assert_status(exc, 409)
    else:
        raise AssertionError("Expected membership mismatch to stale before approver check")

    assert db.settlement_plans.find_one({"id": plan["id"]})["status"] == "stale"


def test_settlement_plan_approve_post_write_snapshot_change_marks_stale_not_approved(
    db, monkeypatch
):
    create_cycle_settlement_source(db)
    service = settlement_service()
    plan = service.create_settlement_plan(db, EVENT_ID, USER_A, idempotency_key="plan")
    service.approve_settlement_plan(db, plan["id"], USER_A)
    service.approve_settlement_plan(db, plan["id"], USER_B)
    original_snapshot = service._snapshot_for_current_state
    calls = 0

    def mutate_before_postcheck(db_arg, event_id, actor_user_id):
        nonlocal calls
        calls += 1
        if calls == 2:
            create_settlement_source_change(db_arg, title="Approve race")
        return original_snapshot(db_arg, event_id, actor_user_id)

    monkeypatch.setattr(service, "_snapshot_for_current_state", mutate_before_postcheck)

    try:
        service.approve_settlement_plan(db, plan["id"], USER_C)
    except Exception as exc:
        assert_status(exc, 409)
    else:
        raise AssertionError("Expected post-write stale approval to fail")

    stored = db.settlement_plans.find_one({"id": plan["id"]})
    assert stored["status"] == "stale"
    assert sorted(approval["user_id"] for approval in stored["approvals"]) == [
        USER_A,
        USER_B,
        USER_C,
    ]
    assert stored.get("active_key") is None


def test_settlement_plan_approve_actor_removed_during_post_validation_marks_stale(db, monkeypatch):
    create_cycle_settlement_source(db)
    service = settlement_service()
    domain_events = []
    monkeypatch.setattr(
        service,
        "record_domain_event",
        lambda domain, action: domain_events.append((domain, action)),
    )
    plan = service.create_settlement_plan(db, EVENT_ID, USER_A, idempotency_key="plan")
    service.approve_settlement_plan(db, plan["id"], USER_A)
    service.approve_settlement_plan(db, plan["id"], USER_B)
    original_snapshot = service._snapshot_for_current_state
    calls = 0

    def remove_actor_before_postcheck(db_arg, event_id, actor_user_id):
        nonlocal calls
        calls += 1
        if calls == 2:
            remove_active_member(db_arg, USER_C)
        return original_snapshot(db_arg, event_id, actor_user_id)

    monkeypatch.setattr(service, "_snapshot_for_current_state", remove_actor_before_postcheck)

    try:
        service.approve_settlement_plan(db, plan["id"], USER_C)
    except Exception as exc:
        assert_status(exc, 409)
    else:
        raise AssertionError("Expected actor removal during approval post-check to fail stale")

    stored = db.settlement_plans.find_one({"id": plan["id"]})
    assert stored["status"] == "stale"
    assert sorted(approval["user_id"] for approval in stored["approvals"]) == [
        USER_A,
        USER_B,
        USER_C,
    ]
    assert stored.get("active_key") is None
    assert audit_action_count(db, "settlement_plan.stale", plan["id"]) == 1
    assert domain_events.count(("settlement_plans", "stale")) == 1


def test_settlement_plan_reject_post_write_snapshot_change_marks_stale_not_rejected(
    db, monkeypatch
):
    create_cycle_settlement_source(db)
    service = settlement_service()
    plan = service.create_settlement_plan(db, EVENT_ID, USER_A, idempotency_key="plan")
    original_snapshot = service._snapshot_for_current_state
    calls = 0

    def mutate_before_postcheck(db_arg, event_id, actor_user_id):
        nonlocal calls
        calls += 1
        if calls == 2:
            create_settlement_source_change(db_arg, title="Reject race")
        return original_snapshot(db_arg, event_id, actor_user_id)

    monkeypatch.setattr(service, "_snapshot_for_current_state", mutate_before_postcheck)

    try:
        service.reject_settlement_plan(db, plan["id"], USER_B, "Race")
    except Exception as exc:
        assert_status(exc, 409)
    else:
        raise AssertionError("Expected post-write stale rejection to fail")

    stored = db.settlement_plans.find_one({"id": plan["id"]})
    assert stored["status"] == "stale"
    assert stored.get("rejected_by") is None
    assert stored.get("rejection_reason") is None
    assert stored.get("active_key") is None


def test_settlement_plan_reject_actor_removed_during_post_validation_marks_stale(db, monkeypatch):
    create_cycle_settlement_source(db)
    service = settlement_service()
    domain_events = []
    monkeypatch.setattr(
        service,
        "record_domain_event",
        lambda domain, action: domain_events.append((domain, action)),
    )
    plan = service.create_settlement_plan(db, EVENT_ID, USER_A, idempotency_key="plan")
    original_snapshot = service._snapshot_for_current_state
    calls = 0

    def remove_actor_before_postcheck(db_arg, event_id, actor_user_id):
        nonlocal calls
        calls += 1
        if calls == 2:
            remove_active_member(db_arg, USER_B)
        return original_snapshot(db_arg, event_id, actor_user_id)

    monkeypatch.setattr(service, "_snapshot_for_current_state", remove_actor_before_postcheck)

    try:
        service.reject_settlement_plan(db, plan["id"], USER_B, "Race")
    except Exception as exc:
        assert_status(exc, 409)
    else:
        raise AssertionError("Expected actor removal during rejection post-check to fail stale")

    stored = db.settlement_plans.find_one({"id": plan["id"]})
    assert stored["status"] == "stale"
    assert stored.get("rejected_by") is None
    assert stored.get("rejection_reason") is None
    assert stored.get("active_key") is None
    assert audit_action_count(db, "settlement_plan.stale", plan["id"]) == 1
    assert domain_events.count(("settlement_plans", "stale")) == 1


def test_settlement_plan_expiry_is_server_transitioned_and_releases_active_guard(db):
    create_cycle_settlement_source(db)
    service = settlement_service()
    plan = service.create_settlement_plan(db, EVENT_ID, USER_A, idempotency_key="plan")
    db.settlement_plans.update_one(
        {"id": plan["id"]},
        {"$set": {"expires_at": datetime(2025, 1, 1, tzinfo=UTC)}},
    )

    expired = service.get_settlement_plan(db, plan["id"], USER_A)
    assert expired["status"] == "expired"
    assert db.settlement_plans.find_one({"id": plan["id"]}).get("active_key") is None

    try:
        service.approve_settlement_plan(db, plan["id"], USER_A)
    except Exception as exc:
        assert_status(exc, 409)
    else:
        raise AssertionError("Expected expired settlement plan approval to fail")

    recreated = service.create_settlement_plan(db, EVENT_ID, USER_B, idempotency_key="new-plan")
    assert recreated["id"] != plan["id"]


def test_settlement_plan_expiry_records_audit_and_domain_once(db, monkeypatch):
    create_cycle_settlement_source(db)
    service = settlement_service()
    domain_events = []
    monkeypatch.setattr(
        service,
        "record_domain_event",
        lambda domain, action: domain_events.append((domain, action)),
    )
    plan = service.create_settlement_plan(db, EVENT_ID, USER_A, idempotency_key="plan")
    db.settlement_plans.update_one(
        {"id": plan["id"]},
        {"$set": {"expires_at": datetime(2025, 1, 1, tzinfo=UTC)}},
    )

    service.get_settlement_plan(db, plan["id"], USER_A)
    service.get_settlement_plan(db, plan["id"], USER_A)

    assert audit_action_count(db, "settlement_plan.expired", plan["id"]) == 1
    assert domain_events.count(("settlement_plans", "expired")) == 1


def test_settlement_plan_rejection_records_audit_and_domain_once(db, monkeypatch):
    create_cycle_settlement_source(db)
    service = settlement_service()
    domain_events = []
    monkeypatch.setattr(
        service,
        "record_domain_event",
        lambda domain, action: domain_events.append((domain, action)),
    )
    plan = service.create_settlement_plan(db, EVENT_ID, USER_A, idempotency_key="plan")

    rejected = service.reject_settlement_plan(db, plan["id"], USER_B, "Need to fix receipt")

    assert rejected["status"] == "rejected"
    assert audit_action_count(db, "settlement_plan.rejected", plan["id"]) == 1
    assert domain_events.count(("settlement_plans", "rejected")) == 1


def test_list_settlement_plans_returns_paginated_event_member_page(db):
    create_cycle_settlement_source(db)
    service = settlement_service()
    first = service.create_settlement_plan(db, EVENT_ID, USER_A, idempotency_key="plan-a")
    service.reject_settlement_plan(db, first["id"], USER_A, "Superseded")
    second = service.create_settlement_plan(db, EVENT_ID, USER_B, idempotency_key="plan-b")

    page = service.list_settlement_plans(db, EVENT_ID, USER_C, limit=1, offset=0)

    assert page["limit"] == 1
    assert page["offset"] == 0
    assert page["total"] == 2
    assert [item["id"] for item in page["items"]] == [second["id"]]


def test_settlement_plan_create_persists_server_edges_without_preview_edge_ids(db):
    create_cycle_settlement_source(db, extra_same_edge=True)
    service = settlement_service()

    plan = service.create_settlement_plan(db, EVENT_ID, USER_A, idempotency_key="plan")

    assert set(plan["preview"]["recommended_transfers"][0]) == {
        "debtor_id",
        "creditor_id",
        "amount_kopecks",
    }
    assert len(plan["edges"]) == 2
    edge_ids = [edge["edge_id"] for edge in plan["edges"]]
    assert len(edge_ids) == len(set(edge_ids))
    for edge, transfer in zip(plan["edges"], plan["preview"]["recommended_transfers"], strict=True):
        assert edge["debtor_id"] == transfer["debtor_id"]
        assert edge["creditor_id"] == transfer["creditor_id"]
        assert edge["amount_kopecks"] == transfer["amount_kopecks"]
        assert edge.get("payment_request_id") is None
        assert edge.get("status") is None

    stored = db.settlement_plans.find_one({"id": plan["id"]})
    assert stored["edges"] == plan["edges"]


def test_settlement_execute_requires_approval_open_event_and_event_member(db):
    create_cycle_settlement_source(db)
    service = settlement_service()
    pending = service.create_settlement_plan(db, EVENT_ID, USER_A, idempotency_key="plan")

    try:
        service.execute_settlement_plan(
            db, pending["id"], USER_A, idempotency_key="execute-before-approval"
        )
    except Exception as exc:
        assert_status(exc, 409)
    else:
        raise AssertionError("Expected execution before approval to fail")

    approved = pending
    for user_id in pending["required_approver_ids"]:
        approved = service.approve_settlement_plan(db, pending["id"], user_id)

    non_member = "44444444-4444-4444-4444-444444444444"
    try:
        service.execute_settlement_plan(
            db, approved["id"], non_member, idempotency_key="execute-non-member"
        )
    except Exception as exc:
        assert_status(exc, 403)
    else:
        raise AssertionError("Expected non-member execution to fail")

    db.events.update_one({"id": EVENT_ID}, {"$set": {"is_closed": True}})
    try:
        service.execute_settlement_plan(
            db, approved["id"], USER_A, idempotency_key="execute-closed"
        )
    except Exception as exc:
        assert_status(exc, 409)
    else:
        raise AssertionError("Expected closed event execution to fail")

    assert db.payment_requests.count_documents({}) == 0


def test_settlement_execute_stales_approved_plan_when_snapshot_changed(db):
    service, approved = create_approved_settlement_plan(db)
    create_settlement_source_change(db)

    try:
        service.execute_settlement_plan(db, approved["id"], USER_B, idempotency_key="execute-stale")
    except Exception as exc:
        assert_status(exc, 409)
    else:
        raise AssertionError("Expected stale approved plan execution to fail")

    stored = db.settlement_plans.find_one({"id": approved["id"]})
    assert stored["status"] == "stale"
    assert stored.get("active_key") is None
    assert db.payment_requests.count_documents({}) == 0


def test_settlement_execute_post_transition_snapshot_race_stales_without_requests(db, monkeypatch):
    service, approved = create_approved_settlement_plan(db)
    original_snapshot = service._snapshot_for_current_state
    calls = 0

    def mutate_after_executing_transition(db_arg, event_id, actor_user_id):
        nonlocal calls
        calls += 1
        if calls == 2:
            create_settlement_source_change(db_arg, title="Execute race")
        return original_snapshot(db_arg, event_id, actor_user_id)

    monkeypatch.setattr(service, "_snapshot_for_current_state", mutate_after_executing_transition)

    try:
        service.execute_settlement_plan(db, approved["id"], USER_A, idempotency_key="execute-race")
    except Exception as exc:
        assert_status(exc, 409)
    else:
        raise AssertionError("Expected post-transition stale execution race to fail")

    stored = db.settlement_plans.find_one({"id": approved["id"]})
    assert calls == 2
    assert stored["status"] == "stale"
    assert stored.get("active_key") is None
    assert stored.get("last_action_id")
    assert db.payment_requests.count_documents({"origin": "settlement_plan"}) == 0
    assert audit_action_count(db, "settlement_plan.stale", approved["id"]) == 1


def test_settlement_execute_rejects_forged_or_mutated_edge_materialization(db):
    service, approved = create_approved_settlement_plan(db)
    stored = db.settlement_plans.find_one({"id": approved["id"]})
    edge_id = stored["edges"][0]["edge_id"]
    db.settlement_plans.update_one(
        {"id": approved["id"], "edges.edge_id": edge_id},
        {"$set": {"edges.$.amount_kopecks": 0}},
    )

    try:
        service._create_or_get_settlement_payment_request(
            db, plan_id=approved["id"], edge_id=edge_id, actor_user_id=USER_A
        )
    except Exception as exc:
        assert_status(exc, 400)
    else:
        raise AssertionError("Expected altered settlement edge materialization to fail")

    assert db.payment_requests.count_documents({}) == 0


def test_settlement_payment_helper_reloads_stored_plan_and_rejects_unknown_edge(db):
    service, approved = create_approved_settlement_plan(db)
    stored_edge = db.settlement_plans.find_one({"id": approved["id"]})["edges"][0]
    forged_edge_id = "99999999-9999-9999-9999-999999999999"

    try:
        service._create_or_get_settlement_payment_request(
            db, plan_id=approved["id"], edge_id=forged_edge_id, actor_user_id=USER_A
        )
    except Exception as exc:
        assert_status(exc, 400)
    else:
        raise AssertionError("Expected forged edge id to fail")

    try:
        payments.create_or_get_settlement_payment_request(
            db,
            plan_id="99999999-9999-9999-9999-999999999998",
            edge_id=stored_edge["edge_id"],
            actor_user_id=USER_A,
        )
    except Exception as exc:
        assert_status(exc, 404)
    else:
        raise AssertionError("Expected synthetic plan id to fail")

    assert db.payment_requests.count_documents({"origin": "settlement_plan"}) == 0


def test_settlement_execute_partial_creation_failure_is_retryable_without_duplicates(
    db, monkeypatch
):
    service, approved = create_approved_settlement_plan(db, extra_same_edge=True)
    original_create = service._create_or_get_settlement_payment_request
    calls = 0

    def fail_second_edge(db_arg, plan_id, edge_id, actor_user_id):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("simulated payment request failure")
        return original_create(db_arg, plan_id, edge_id, actor_user_id)

    monkeypatch.setattr(service, "_create_or_get_settlement_payment_request", fail_second_edge)
    try:
        service.execute_settlement_plan(db, approved["id"], USER_A, idempotency_key="execute-fail")
    except RuntimeError as exc:
        assert str(exc) == "simulated payment request failure"
    else:
        raise AssertionError("Expected partial payment request creation failure")

    after_failure = db.settlement_plans.find_one({"id": approved["id"]})
    assert after_failure["status"] == "executing"
    assert sum(1 for edge in after_failure["edges"] if edge.get("payment_request_id")) == 1
    assert db.payment_requests.count_documents({}) == 1

    monkeypatch.setattr(service, "_create_or_get_settlement_payment_request", original_create)
    retried = service.execute_settlement_plan(db, approved["id"], USER_B, idempotency_key="retry")

    assert retried["status"] == "executing"
    assert [edge["status"] for edge in retried["edges"]] == ["requested", "requested"]
    assert db.payment_requests.count_documents({}) == 2
    assert audit_action_count(db, "settlement_plan.executing", approved["id"]) == 1
    assert audit_action_total(db, "payment_request.created") == 2


def test_settlement_execute_same_and_different_actor_keys_link_existing_request_once(db):
    service, approved = create_approved_settlement_plan(db)

    first = service.execute_settlement_plan(db, approved["id"], USER_A, idempotency_key="execute-a")
    same_key = service.execute_settlement_plan(
        db, approved["id"], USER_A, idempotency_key="execute-a"
    )
    different_actor = service.execute_settlement_plan(
        db, approved["id"], USER_B, idempotency_key="execute-b"
    )

    first_request_id = first["edges"][0]["payment_request_id"]
    assert same_key["edges"][0]["payment_request_id"] == first_request_id
    assert different_actor["edges"][0]["payment_request_id"] == first_request_id
    assert db.payment_requests.count_documents({}) == 1
    assert audit_action_count(db, "settlement_plan.executing", approved["id"]) == 1
    assert audit_action_total(db, "payment_request.created") == 1


def test_settlement_execute_replay_requires_current_member_before_idempotency_cache(db):
    service, approved = create_approved_settlement_plan(db)
    first = service.execute_settlement_plan(db, approved["id"], USER_A, idempotency_key="execute-a")
    remove_active_member(db, USER_A)

    try:
        service.execute_settlement_plan(db, approved["id"], USER_A, idempotency_key="execute-a")
    except Exception as exc:
        assert_status(exc, 403)
    else:
        raise AssertionError("Expected removed member execute replay to fail before cache replay")

    assert db.payment_requests.count_documents({"id": first["edges"][0]["payment_request_id"]}) == 1


def test_settlement_execute_replay_requires_open_event_even_when_completed(db):
    service, approved = create_approved_settlement_plan(db)
    executed = service.execute_settlement_plan(
        db, approved["id"], USER_A, idempotency_key="execute"
    )
    edge = executed["edges"][0]
    payment = payments.mark_payment_request_paid(
        db,
        edge["payment_request_id"],
        edge["debtor_id"],
        idempotency_key="mark-paid",
    )
    payments.confirm_payment(db, payment["id"], edge["creditor_id"])
    assert service.get_settlement_plan(db, approved["id"], USER_A)["status"] == "completed"
    db.events.update_one({"id": EVENT_ID}, {"$set": {"is_closed": True}})

    try:
        service.execute_settlement_plan(db, approved["id"], USER_A, idempotency_key="execute")
    except Exception as exc:
        assert_status(exc, 409)
    else:
        raise AssertionError("Expected closed event execute replay to fail before cache replay")


def test_settlement_execute_links_exact_payment_request_provenance_without_payment(db):
    service, approved = create_approved_settlement_plan(db)

    executed = service.execute_settlement_plan(
        db, approved["id"], USER_C, idempotency_key="execute-provenance"
    )

    edge = executed["edges"][0]
    request = db.payment_requests.find_one({"id": edge["payment_request_id"]})
    assert executed["status"] == "executing"
    assert edge["status"] == "requested"
    assert request["origin"] == "settlement_plan"
    assert request["settlement_plan_id"] == approved["id"]
    assert request["settlement_edge_id"] == edge["edge_id"]
    assert request["debtor_id"] == edge["debtor_id"]
    assert request["creditor_id"] == edge["creditor_id"]
    assert request["amount_kopecks"] == edge["amount_kopecks"]
    assert request["created_by"] == USER_C
    assert "optimized event settlement" in request["note"]
    assert db.payments.count_documents({}) == 0


def test_settlement_one_edge_mark_paid_then_confirm_completes_plan(db):
    service, approved = create_approved_settlement_plan(db)
    executed = service.execute_settlement_plan(
        db, approved["id"], USER_A, idempotency_key="execute"
    )
    edge = executed["edges"][0]

    payment = payments.mark_payment_request_paid(
        db,
        edge["payment_request_id"],
        edge["debtor_id"],
        idempotency_key="mark-paid",
    )
    paid_plan = service.get_settlement_plan(db, approved["id"], USER_A)

    assert payment["status"] == "pending"
    assert paid_plan["status"] == "executing"
    assert paid_plan["edges"][0]["status"] == "paid"

    payments.confirm_payment(db, payment["id"], edge["creditor_id"])
    completed = service.get_settlement_plan(db, approved["id"], USER_A)

    assert completed["status"] == "completed"
    assert completed["edges"][0]["status"] == "confirmed"
    assert audit_action_count(db, "settlement_plan.completed", approved["id"]) == 1


def test_settlement_multi_edge_progresses_partial_then_completed(db):
    service, approved = create_approved_settlement_plan(db, extra_same_edge=True)
    executed = service.execute_settlement_plan(
        db, approved["id"], USER_A, idempotency_key="execute"
    )
    first_edge, second_edge = executed["edges"]

    first_payment = payments.mark_payment_request_paid(
        db,
        first_edge["payment_request_id"],
        first_edge["debtor_id"],
        idempotency_key="mark-first",
    )
    payments.confirm_payment(db, first_payment["id"], first_edge["creditor_id"])
    partial = service.get_settlement_plan(db, approved["id"], USER_A)

    assert partial["status"] == "partially_settled"
    assert [edge["status"] for edge in partial["edges"]] == ["confirmed", "requested"]

    second_payment = payments.mark_payment_request_paid(
        db,
        second_edge["payment_request_id"],
        second_edge["debtor_id"],
        idempotency_key="mark-second",
    )
    payments.confirm_payment(db, second_payment["id"], second_edge["creditor_id"])
    completed = service.get_settlement_plan(db, approved["id"], USER_B)

    assert completed["status"] == "completed"
    assert [edge["status"] for edge in completed["edges"]] == ["confirmed", "confirmed"]
    assert audit_action_count(db, "settlement_plan.partially_settled", approved["id"]) == 1
    assert audit_action_count(db, "settlement_plan.completed", approved["id"]) == 1


def test_settlement_rejected_payment_remains_visible_and_not_completed(db):
    service, approved = create_approved_settlement_plan(db)
    executed = service.execute_settlement_plan(
        db, approved["id"], USER_A, idempotency_key="execute"
    )
    edge = executed["edges"][0]
    payment = payments.mark_payment_request_paid(
        db,
        edge["payment_request_id"],
        edge["debtor_id"],
        idempotency_key="mark-paid",
    )

    payments.reject_payment(db, payment["id"], edge["creditor_id"])
    refreshed = service.get_settlement_plan(db, approved["id"], USER_A)

    assert refreshed["status"] == "executing"
    assert refreshed["edges"][0]["payment_request_id"] == edge["payment_request_id"]
    assert refreshed["edges"][0]["status"] == "rejected"
    assert audit_action_count(db, "settlement_plan.partially_settled", approved["id"]) == 0
    assert audit_action_count(db, "settlement_plan.completed", approved["id"]) == 0


def test_settlement_payment_patch_confirms_linked_request_and_completes_plan(db):
    service, approved = create_approved_settlement_plan(db)
    executed = service.execute_settlement_plan(
        db, approved["id"], USER_A, idempotency_key="execute-patch-confirm"
    )
    edge = executed["edges"][0]
    payment = payments.mark_payment_request_paid(
        db,
        edge["payment_request_id"],
        edge["debtor_id"],
        idempotency_key="mark-paid-patch-confirm",
    )

    confirmed = payments.update_payment(
        db, payment["id"], schemas.PaymentUpdate(confirmed=True), edge["creditor_id"]
    )

    assert confirmed["status"] == "confirmed"
    assert db.payment_requests.find_one({"id": edge["payment_request_id"]})["status"] == "confirmed"
    assert service.get_settlement_plan(db, approved["id"], USER_A)["status"] == "completed"


def test_rejected_payment_cannot_be_confirmed_without_new_payment(db):
    service, approved = create_approved_settlement_plan(db)
    executed = service.execute_settlement_plan(
        db, approved["id"], USER_A, idempotency_key="execute-rejected-confirm"
    )
    edge = executed["edges"][0]
    payment = payments.mark_payment_request_paid(
        db,
        edge["payment_request_id"],
        edge["debtor_id"],
        idempotency_key="mark-paid-rejected-confirm",
    )
    payments.reject_payment(db, payment["id"], edge["creditor_id"])

    try:
        payments.confirm_payment(db, payment["id"], edge["creditor_id"])
    except Exception as exc:
        assert_status(exc, 409)
    else:
        raise AssertionError("Expected rejected payment confirmation to fail")

    assert db.payment_requests.find_one({"id": edge["payment_request_id"]})["status"] == "rejected"


def test_disputed_payment_request_blocks_linked_payment_confirmation(db):
    service, approved = create_approved_settlement_plan(db)
    executed = service.execute_settlement_plan(
        db, approved["id"], USER_A, idempotency_key="execute-disputed-confirm"
    )
    edge = executed["edges"][0]
    payment = payments.mark_payment_request_paid(
        db,
        edge["payment_request_id"],
        edge["debtor_id"],
        idempotency_key="mark-paid-disputed-confirm",
    )
    payments.dispute_payment_request(db, edge["payment_request_id"], edge["debtor_id"])

    try:
        payments.confirm_payment(db, payment["id"], edge["creditor_id"])
    except Exception as exc:
        assert_status(exc, 409)
    else:
        raise AssertionError("Expected disputed payment confirmation to fail")

    assert db.payment_requests.find_one({"id": edge["payment_request_id"]})["status"] == "disputed"


def test_settlement_confirm_refresh_failure_does_not_rollback_money_audit_or_domain(
    db, monkeypatch
):
    service, approved = create_approved_settlement_plan(db)
    executed = service.execute_settlement_plan(
        db, approved["id"], USER_A, idempotency_key="execute"
    )
    edge = executed["edges"][0]
    payment = payments.mark_payment_request_paid(
        db,
        edge["payment_request_id"],
        edge["debtor_id"],
        idempotency_key="mark-paid",
    )
    domain_events = []
    monkeypatch.setattr(
        payments,
        "record_domain_event",
        lambda domain, action: domain_events.append((domain, action)),
    )
    monkeypatch.setattr(
        payments,
        "_refresh_settlement_progress_for_request",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("refresh failed")),
    )

    confirmed = payments.confirm_payment(db, payment["id"], edge["creditor_id"])

    payment_request = db.payment_requests.find_one({"id": edge["payment_request_id"]})
    assert confirmed["status"] == "confirmed"
    assert confirmed["confirmed"] is True
    assert payment_request["status"] == "confirmed"
    assert audit_action_count(db, "payment.confirmed", payment["id"]) == 1
    assert domain_events == [("payments", "confirmed")]


def test_settlement_reject_refresh_failure_does_not_rollback_money_audit_or_domain(db, monkeypatch):
    service, approved = create_approved_settlement_plan(db)
    executed = service.execute_settlement_plan(
        db, approved["id"], USER_A, idempotency_key="execute"
    )
    edge = executed["edges"][0]
    payment = payments.mark_payment_request_paid(
        db,
        edge["payment_request_id"],
        edge["debtor_id"],
        idempotency_key="mark-paid",
    )
    domain_events = []
    monkeypatch.setattr(
        payments,
        "record_domain_event",
        lambda domain, action: domain_events.append((domain, action)),
    )
    monkeypatch.setattr(
        payments,
        "_refresh_settlement_progress_for_request",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("refresh failed")),
    )

    rejected = payments.reject_payment(db, payment["id"], edge["creditor_id"])

    payment_request = db.payment_requests.find_one({"id": edge["payment_request_id"]})
    assert rejected["status"] == "rejected"
    assert rejected["confirmed"] is False
    assert payment_request["status"] == "rejected"
    assert audit_action_count(db, "payment.rejected", payment["id"]) == 1
    assert domain_events == [("payments", "rejected")]


def test_settlement_public_payment_request_authorization_rule_is_unchanged(db):
    seed_event(db)

    try:
        payments.create_payment_request(
            db,
            EVENT_ID,
            schemas.PaymentRequestCreate(
                debtor_id=USER_B,
                creditor_id=USER_A,
                amount_kopecks=3000,
                note="Ordinary request",
            ),
            USER_B,
            idempotency_key="ordinary-forbidden",
        )
    except Exception as exc:
        assert_status(exc, 403)
    else:
        raise AssertionError("Expected non-creditor public payment request creation to fail")

    forged_payload = schemas.PaymentRequestCreate.model_validate(
        {
            "debtor_id": USER_B,
            "creditor_id": USER_A,
            "amount_kopecks": 3000,
            "note": "Ordinary request",
            "origin": "settlement_plan",
            "settlement_plan_id": "aaaaaaaa-0000-0000-0000-000000000099",
            "settlement_edge_id": "aaaaaaaa-0000-0000-0000-000000000100",
        }
    )
    request = payments.create_payment_request(
        db,
        EVENT_ID,
        forged_payload,
        USER_A,
        idempotency_key="ordinary-allowed",
    )

    stored = db.payment_requests.find_one({"id": request["id"]})
    assert request["created_by"] == USER_A
    assert "origin" not in request
    assert "settlement_plan_id" not in request
    assert "settlement_edge_id" not in request
    assert "origin" not in stored
    assert "settlement_plan_id" not in stored
    assert "settlement_edge_id" not in stored


def test_confirmed_receipt_financial_fields_cannot_be_changed(db):
    seed_event(db)
    receipt = receipts.create_receipt(db, EVENT_ID, receipt_payload(), USER_A)
    confirm_receipt_for_all(db, receipt["id"])

    try:
        receipts.update_receipt(
            db,
            receipt["id"],
            schemas.UpdateReceiptRequest(total_amount_kopecks=10000, items=receipt_payload().items),
            USER_A,
        )
    except Exception as exc:
        assert_status(exc, 409)
    else:
        raise AssertionError("Expected confirmed receipt financial update to fail")

    updated = receipts.update_receipt(
        db,
        receipt["id"],
        schemas.UpdateReceiptRequest(title="Updated title"),
        USER_A,
    )

    assert updated["title"] == "Updated title"
    assert updated["status"] == "confirmed"


def test_receipt_update_rejects_stale_version(db):
    seed_event(db)
    receipt = receipts.create_receipt(db, EVENT_ID, receipt_payload(), USER_A)
    updated = receipts.update_receipt(
        db,
        receipt["id"],
        schemas.UpdateReceiptRequest(title="First", expected_version=1),
        USER_A,
    )

    try:
        receipts.update_receipt(
            db,
            receipt["id"],
            schemas.UpdateReceiptRequest(title="Stale", expected_version=1),
            USER_A,
        )
    except Exception as exc:
        assert_status(exc, 409)
    else:
        raise AssertionError("Expected stale receipt version update to fail")

    assert updated["version"] == 2


def test_voided_receipt_no_longer_affects_balances(db):
    seed_event(db)
    receipt = receipts.create_receipt(db, EVENT_ID, receipt_payload(), USER_A)
    confirm_receipt_for_all(db, receipt["id"])

    assert balances.get_event_balances(db, EVENT_ID, USER_A)

    voided = receipts.void_receipt(db, receipt["id"], USER_A)

    assert voided["status"] == "voided"
    assert balances.get_event_balances(db, EVENT_ID, USER_A) == []


def test_receipt_correction_marks_original_and_creates_draft(db):
    seed_event(db)
    receipt = receipts.create_receipt(db, EVENT_ID, receipt_payload(), USER_A)
    confirm_receipt_for_all(db, receipt["id"])

    correction = receipts.create_receipt_correction(db, receipt["id"], USER_A)

    original = receipts.get_receipt(db, receipt["id"], USER_A)
    assert original["status"] == "corrected"
    assert correction["status"] == "draft"
    assert correction["corrected_from_receipt_id"] == receipt["id"]
    assert balances.get_event_balances(db, EVENT_ID, USER_A) == []


def test_allocation_session_claim_finalize_and_confirm(db):
    seed_event(db)
    payload = schemas.CreateReceiptRequest(
        payer_id=USER_A,
        title="Allocation",
        total_amount_kopecks=3000,
        items=[
            schemas.CreateReceiptItemRequest(
                name="Shared",
                cost_kopecks=3000,
                share_items=[schemas.CreateShareItemRequest(user_id=USER_A, share_value="1")],
            )
        ],
    )
    receipt = receipts.create_receipt(db, EVENT_ID, payload, USER_A)
    item_id = receipt["items"][0]["id"]

    state = receipts.start_allocation_session(db, receipt["id"], USER_A)
    claim_a = receipts.claim_receipt_item(
        db,
        state["session"]["id"],
        schemas.ReceiptItemClaimRequest(receipt_item_id=item_id),
        USER_A,
    )
    claim_b = receipts.claim_receipt_item(
        db,
        state["session"]["id"],
        schemas.ReceiptItemClaimRequest(receipt_item_id=item_id),
        USER_B,
    )
    ready = receipts.mark_allocation_session_ready(db, state["session"]["id"], USER_A)
    finalized = receipts.finalize_allocation_session(db, state["session"]["id"], USER_A)

    assert claim_a["user_id"] == USER_A
    assert claim_b["user_id"] == USER_B
    assert ready["session"]["status"] == "ready"
    assert finalized["status"] == "ready_for_review"
    assert finalized["items"][0]["split_mode"] == "selected_equal"
    assert balances.get_event_balances(db, EVENT_ID, USER_A) == []

    confirmed, _ = confirm_receipt_for_all(db, receipt["id"])
    rows = balances.get_event_balances(db, EVENT_ID, USER_A)

    assert confirmed["status"] == "confirmed"
    assert rows == [
        {
            "event_id": EVENT_ID,
            "debitor_id": USER_B,
            "creditor_id": USER_A,
            "amount_kopecks": 1500,
        }
    ]


def test_allocation_session_unclaim_requires_every_item_claimed(db):
    seed_event(db)
    receipt = receipts.create_receipt(db, EVENT_ID, receipt_payload(), USER_A)
    item_id = receipt["items"][0]["id"]
    state = receipts.start_allocation_session(db, receipt["id"], USER_A)
    receipts.claim_receipt_item(
        db,
        state["session"]["id"],
        schemas.ReceiptItemClaimRequest(receipt_item_id=item_id),
        USER_B,
    )

    receipts.unclaim_receipt_item(
        db,
        state["session"]["id"],
        schemas.ReceiptItemClaimRequest(receipt_item_id=item_id),
        USER_B,
    )

    try:
        receipts.finalize_allocation_session(db, state["session"]["id"], USER_A)
    except Exception as exc:
        assert_status(exc, 400)
    else:
        raise AssertionError("Expected allocation finalize without claims to fail")


def test_legacy_decimal_money_storage_reads_as_kopecks(db):
    seed_event(db)
    db.receipts.insert_one(
        {
            "id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            "event_id": EVENT_ID,
            "payer_id": USER_A,
            "title": "Legacy",
            "total_amount": "10.25",
            "created_at": datetime(2026, 1, 1, tzinfo=UTC),
            "updated_at": datetime(2026, 1, 1, tzinfo=UTC),
            "items": [
                {
                    "id": "item-1",
                    "receipt_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                    "name": "Legacy item",
                    "cost": "10.25",
                    "share_items": ["share-1"],
                }
            ],
            "share_items": [
                {
                    "id": "share-1",
                    "receipt_item_id": "item-1",
                    "user_id": USER_B,
                    "share_value": "1",
                }
            ],
        }
    )
    db.payments.insert_one(
        {
            "id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
            "event_id": EVENT_ID,
            "sender_id": USER_B,
            "receiver_id": USER_A,
            "amount": "1.25",
            "confirmed": True,
            "created_at": datetime(2026, 1, 2, tzinfo=UTC),
        }
    )

    receipt = receipts.get_receipt(db, "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", USER_A)
    payment_page = payments.list_payments_by_event(db, EVENT_ID, USER_A, limit=50, offset=0)
    rows = balances.get_event_balances(db, EVENT_ID, USER_A)

    assert receipt["total_amount_kopecks"] == 1025
    assert receipt["items"][0]["cost_kopecks"] == 1025
    assert payment_page["items"][0]["amount_kopecks"] == 125
    assert rows == [
        {
            "event_id": EVENT_ID,
            "debitor_id": USER_B,
            "creditor_id": USER_A,
            "amount_kopecks": 900,
        }
    ]


def test_receipt_image_upload_presign_and_delete(db, fake_s3, monkeypatch):
    monkeypatch.setenv("S3_BUCKET", "split-bucket")
    seed_event(db)
    receipt = receipts.create_receipt(db, EVENT_ID, receipt_payload(), USER_A)

    upload = receipt_image.upload_receipt_image(
        db,
        fake_s3,
        receipt["id"],
        b"\xff\xd8\xffjpeg",
        "image/jpeg",
        USER_A,
    )
    stored = db.receipts.find_one({"id": receipt["id"]})
    presigned = receipt_image.get_receipt_image_presigned_url(db, fake_s3, receipt["id"], USER_B)
    uploaded_object = fake_s3.objects[("split-bucket", stored["image_key"])]

    receipt_image.delete_receipt_image(db, fake_s3, receipt["id"], USER_A)
    after_delete = db.receipts.find_one({"id": receipt["id"]})

    assert "image_url" not in stored
    assert upload["image_url"].startswith("https://signed.example/")
    assert stored["image_key"] in upload["image_url"]
    assert "ACL" not in uploaded_object
    assert presigned["image_url"].startswith("https://signed.example/")
    assert fake_s3.deleted == [("split-bucket", stored["image_key"])]
    assert "image_url" not in after_delete
    assert "image_key" not in after_delete


def test_receipt_image_replacement_deletes_previous_object(db, fake_s3, monkeypatch):
    monkeypatch.setenv("S3_BUCKET", "split-bucket")
    seed_event(db)
    receipt = receipts.create_receipt(db, EVENT_ID, receipt_payload(), USER_A)

    receipt_image.upload_receipt_image(
        db,
        fake_s3,
        receipt["id"],
        b"\xff\xd8\xfffirst",
        "image/jpeg",
        USER_A,
    )
    first = db.receipts.find_one({"id": receipt["id"]})

    receipt_image.upload_receipt_image(
        db,
        fake_s3,
        receipt["id"],
        b"\xff\xd8\xffsecond",
        "image/jpeg",
        USER_A,
    )
    second = db.receipts.find_one({"id": receipt["id"]})

    assert first["image_key"] != second["image_key"]
    assert fake_s3.deleted == [("split-bucket", first["image_key"])]
    assert ("split-bucket", first["image_key"]) not in fake_s3.objects
    assert ("split-bucket", second["image_key"]) in fake_s3.objects


def test_payment_create_and_confirm(db):
    seed_event(db)
    payment = payments.create_payment(db, EVENT_ID, payment_payload(), USER_A)

    updated = payments.update_payment(
        db,
        payment["id"],
        schemas.PaymentUpdate(confirmed=True),
        USER_B,
    )

    assert updated["confirmed"] is True


def test_payment_create_is_idempotent_for_same_key_and_payload(db):
    seed_event(db)
    payload = payment_payload()

    first = payments.create_payment(
        db, EVENT_ID, payload, USER_A, idempotency_key="payment-create-1"
    )
    second = payments.create_payment(
        db, EVENT_ID, payload, USER_A, idempotency_key="payment-create-1"
    )

    assert second == first
    assert db.payments.count_documents({"event_id": EVENT_ID}) == 1
    assert db.idempotency_keys.count_documents({}) == 1


def test_payment_create_rejects_idempotency_key_reuse_with_different_payload(db):
    seed_event(db)
    payments.create_payment(
        db, EVENT_ID, payment_payload(), USER_A, idempotency_key="payment-create-1"
    )
    changed_payload = schemas.PaymentCreate(
        sender_id=USER_A, receiver_id=USER_B, amount_kopecks=5100
    )

    try:
        payments.create_payment(
            db, EVENT_ID, changed_payload, USER_A, idempotency_key="payment-create-1"
        )
    except Exception as exc:
        assert_status(exc, 409)
    else:
        raise AssertionError("Expected idempotency key reuse with different payload to fail")


def test_idempotency_key_in_progress_blocks_duplicate_create(db):
    payload = {"value": 1}
    db.idempotency_keys.insert_one(
        {
            "actor_user_id": USER_A,
            "scope": "test-scope",
            "key": "in-flight",
            "request_hash": _request_hash(payload),
            "status": "in_progress",
        }
    )

    try:
        run_idempotent_create(
            db,
            actor_user_id=USER_A,
            scope="test-scope",
            key="in-flight",
            request_payload=payload,
            create=lambda: {"ok": True},
        )
    except Exception as exc:
        assert_status(exc, 409)
    else:
        raise AssertionError("Expected in-progress idempotency key to reject duplicate create")


def test_idempotency_reservation_is_removed_after_create_failure(db):
    def fail_create():
        raise RuntimeError("create failed")

    try:
        run_idempotent_create(
            db,
            actor_user_id=USER_A,
            scope="test-scope",
            key="retryable",
            request_payload={"value": 1},
            create=fail_create,
        )
    except RuntimeError:
        pass
    else:
        raise AssertionError("Expected create failure")

    response = run_idempotent_create(
        db,
        actor_user_id=USER_A,
        scope="test-scope",
        key="retryable",
        request_payload={"value": 1},
        create=lambda: {"ok": True},
    )

    assert response == {"ok": True}


def test_payment_request_mark_paid_confirm_and_balance_impact(db):
    seed_event(db)
    receipt = receipts.create_receipt(db, EVENT_ID, receipt_payload(), USER_A)
    confirm_receipt_for_all(db, receipt["id"])
    request = payments.create_payment_request(
        db,
        EVENT_ID,
        schemas.PaymentRequestCreate(
            debtor_id=USER_B,
            creditor_id=USER_A,
            amount_kopecks=3000,
            note="Dinner share",
        ),
        USER_A,
        idempotency_key="request-1",
    )

    repeated_request = payments.create_payment_request(
        db,
        EVENT_ID,
        schemas.PaymentRequestCreate(
            debtor_id=USER_B,
            creditor_id=USER_A,
            amount_kopecks=3000,
            note="Dinner share",
        ),
        USER_A,
        idempotency_key="request-1",
    )
    payment = payments.mark_payment_request_paid(
        db, request["id"], USER_B, idempotency_key="mark-paid-1"
    )
    repeated_payment = payments.mark_payment_request_paid(
        db, request["id"], USER_B, idempotency_key="mark-paid-1"
    )

    assert repeated_request == request
    assert repeated_payment == payment
    assert payment["sender_id"] == USER_B
    assert payment["receiver_id"] == USER_A
    assert payment["status"] == "pending"
    assert balances.get_event_balances(db, EVENT_ID, USER_A)[0]["amount_kopecks"] == 5000

    confirmed = payments.confirm_payment(db, payment["id"], USER_A)

    assert confirmed["status"] == "confirmed"
    assert confirmed["confirmed"] is True
    assert db.payment_requests.find_one({"id": request["id"]})["status"] == "confirmed"
    assert balances.get_event_balances(db, EVENT_ID, USER_A)[0]["amount_kopecks"] == 2000


def test_payment_request_reject_flow_does_not_reduce_balance(db):
    seed_event(db)
    receipt = receipts.create_receipt(db, EVENT_ID, receipt_payload(), USER_A)
    confirm_receipt_for_all(db, receipt["id"])
    request = payments.create_payment_request(
        db,
        EVENT_ID,
        schemas.PaymentRequestCreate(debtor_id=USER_B, creditor_id=USER_A, amount_kopecks=3000),
        USER_A,
        idempotency_key="request-1",
    )
    payment = payments.mark_payment_request_paid(
        db, request["id"], USER_B, idempotency_key="mark-paid-1"
    )

    rejected = payments.reject_payment(db, payment["id"], USER_A)

    assert rejected["status"] == "rejected"
    assert rejected["confirmed"] is False
    assert db.payment_requests.find_one({"id": request["id"]})["status"] == "rejected"
    assert balances.get_event_balances(db, EVENT_ID, USER_A)[0]["amount_kopecks"] == 5000


def test_payment_request_requires_creditor_actor_and_debtor_mark_paid(db):
    seed_event(db)

    try:
        payments.create_payment_request(
            db,
            EVENT_ID,
            schemas.PaymentRequestCreate(debtor_id=USER_B, creditor_id=USER_A, amount_kopecks=3000),
            USER_B,
        )
    except Exception as exc:
        assert_status(exc, 403)
    else:
        raise AssertionError("Expected non-creditor payment request creation to fail")

    request = payments.create_payment_request(
        db,
        EVENT_ID,
        schemas.PaymentRequestCreate(debtor_id=USER_B, creditor_id=USER_A, amount_kopecks=3000),
        USER_A,
    )
    try:
        payments.mark_payment_request_paid(db, request["id"], USER_A)
    except Exception as exc:
        assert_status(exc, 403)
    else:
        raise AssertionError("Expected non-debtor mark-paid to fail")


def test_payment_request_deadline_acknowledge_extension_cancel_and_dispute(db):
    seed_event(db)
    deadline = datetime.now(UTC) + timedelta(hours=1)
    request = payments.create_payment_request(
        db,
        EVENT_ID,
        schemas.PaymentRequestCreate(
            debtor_id=USER_B,
            creditor_id=USER_A,
            amount_kopecks=3000,
            deadline_at=deadline,
        ),
        USER_A,
    )

    acknowledged = payments.acknowledge_payment_request(db, request["id"], USER_B)
    extended = payments.request_payment_extension(db, request["id"], USER_B)
    disputed = payments.dispute_payment_request(db, request["id"], USER_B)

    assert acknowledged["acknowledged_at"] is not None
    assert extended["extension_requested_at"] is not None
    assert disputed["status"] == "disputed"
    assert disputed["disputed_at"] is not None

    cancelled = payments.cancel_payment_request(db, request["id"], USER_A)
    assert cancelled["status"] == "cancelled"
    assert cancelled["cancelled_at"] is not None


def test_cancelling_paid_payment_request_voids_linked_pending_payment(db):
    seed_event(db)
    request = payments.create_payment_request(
        db,
        EVENT_ID,
        schemas.PaymentRequestCreate(
            debtor_id=USER_B,
            creditor_id=USER_A,
            amount_kopecks=5000,
        ),
        USER_A,
        idempotency_key="request-cancel-linked-payment",
    )
    payment = payments.mark_payment_request_paid(
        db,
        request["id"],
        USER_B,
        idempotency_key="mark-paid-cancel-linked-payment",
    )

    cancelled = payments.cancel_payment_request(db, request["id"], USER_A)

    stored_payment = db.payments.find_one({"id": payment["id"]})
    assert cancelled["status"] == "cancelled"
    assert stored_payment["deleted_at"] is not None
    try:
        payments.confirm_payment(db, payment["id"], USER_A)
    except Exception as exc:
        assert_status(exc, 404)
    else:
        raise AssertionError("Expected cancelled linked payment confirmation to fail")


def test_home_summary_separates_confirmed_pending_and_disputed_money(db):
    seed_event(db)
    confirmed_receipt = receipts.create_receipt(db, EVENT_ID, receipt_payload(), USER_A)
    confirm_receipt_for_all(db, confirmed_receipt["id"])
    pending_receipt = receipts.create_receipt(db, EVENT_ID, receipt_payload(), USER_A)
    receipts.validate_receipt(db, pending_receipt["id"], USER_A)
    disputed_receipt = receipts.create_receipt(db, EVENT_ID, receipt_payload(), USER_A)
    receipts.validate_receipt(db, disputed_receipt["id"], USER_A)
    receipts.dispute_receipt_share_review(
        db,
        disputed_receipt["id"],
        schemas.ReceiptShareReviewDispute(reason="Not mine"),
        USER_B,
    )
    payments.create_payment_request(
        db,
        EVENT_ID,
        schemas.PaymentRequestCreate(debtor_id=USER_B, creditor_id=USER_A, amount_kopecks=1000),
        USER_A,
    )

    summary_a = home.get_home_summary(db, USER_A)
    summary_b = home.get_home_summary(db, USER_B)

    assert summary_a["confirmed"]["receivable_kopecks"] == 5000
    assert summary_b["confirmed"]["owed_kopecks"] == 5000
    assert summary_a["pending"]["receivable_kopecks"] == 6000
    assert summary_b["pending"]["owed_kopecks"] == 6000
    assert summary_a["disputed"]["receivable_kopecks"] == 5000
    assert summary_b["disputed"]["owed_kopecks"] == 5000


def test_payment_request_deadline_must_be_at_least_30_minutes(db):
    seed_event(db)

    try:
        payments.create_payment_request(
            db,
            EVENT_ID,
            schemas.PaymentRequestCreate(
                debtor_id=USER_B,
                creditor_id=USER_A,
                amount_kopecks=3000,
                deadline_at=datetime.now(UTC) + timedelta(minutes=10),
            ),
            USER_A,
        )
    except Exception as exc:
        assert_status(exc, 400)
    else:
        raise AssertionError("Expected too-soon deadline to fail")


def test_payment_request_lifecycle_authorization(db):
    seed_event(db)
    request = payments.create_payment_request(
        db,
        EVENT_ID,
        schemas.PaymentRequestCreate(debtor_id=USER_B, creditor_id=USER_A, amount_kopecks=3000),
        USER_A,
    )

    for action in (
        lambda: payments.acknowledge_payment_request(db, request["id"], USER_A),
        lambda: payments.request_payment_extension(db, request["id"], USER_A),
        lambda: payments.cancel_payment_request(db, request["id"], USER_B),
    ):
        try:
            action()
        except Exception as exc:
            assert_status(exc, 403)
        else:
            raise AssertionError("Expected unauthorized payment request lifecycle action to fail")


def test_dispute_create_list_and_creator_resolve(db):
    seed_event(db)
    receipt = receipts.create_receipt(db, EVENT_ID, receipt_payload(), USER_A)

    dispute = disputes.create_dispute(
        db,
        schemas.DisputeCreate(
            resource_type="receipt",
            resource_id=receipt["id"],
            reason="Wrong split",
        ),
        USER_B,
    )
    page = disputes.list_event_disputes(db, EVENT_ID, USER_A, limit=50, offset=0)

    assert dispute["status"] == "open"
    assert page["items"][0]["id"] == dispute["id"]

    try:
        disputes.resolve_dispute(
            db, dispute["id"], schemas.DisputeResolve(resolution_note="Fixed"), USER_B
        )
    except Exception as exc:
        assert_status(exc, 403)
    else:
        raise AssertionError("Expected non-creator dispute resolve to fail")

    resolved = disputes.resolve_dispute(
        db, dispute["id"], schemas.DisputeResolve(resolution_note="Fixed"), USER_A
    )

    assert resolved["status"] == "resolved"
    assert resolved["resolved_by"] == USER_A
    assert resolved["resolution_note"] == "Fixed"


def test_dispute_requires_event_membership_and_valid_resource(db):
    seed_event(db)
    receipt = receipts.create_receipt(db, EVENT_ID, receipt_payload(), USER_A)

    try:
        disputes.create_dispute(
            db,
            schemas.DisputeCreate(
                resource_type="receipt",
                resource_id=receipt["id"],
                reason="Wrong split",
            ),
            USER_C,
        )
    except Exception as exc:
        assert_status(exc, 403)
    else:
        raise AssertionError("Expected non-member dispute creation to fail")

    with pytest.raises(ValidationError):
        schemas.DisputeCreate(
            resource_type="unknown",
            resource_id=receipt["id"],
            reason="Wrong split",
        )


def test_event_activity_feed_lists_related_audit_events_for_members(db):
    seed_event(db)
    receipt = receipts.create_receipt(db, EVENT_ID, receipt_payload(), USER_A)
    confirm_receipt_for_all(db, receipt["id"])
    payment = payments.create_payment(db, EVENT_ID, payment_payload(), USER_A)
    payments.confirm_payment(db, payment["id"], USER_B)

    page = audit.list_event_activity(db, EVENT_ID, USER_A, limit=50, offset=0)
    actions = {item["action"] for item in page["items"]}

    assert {"receipt.confirmed", "payment.confirmed"}.issubset(actions)
    try:
        audit.list_event_activity(db, EVENT_ID, USER_C, limit=50, offset=0)
    except Exception as exc:
        assert_status(exc, 403)
    else:
        raise AssertionError("Expected non-member activity feed access to fail")


def test_only_payment_receiver_can_confirm_or_reject_payment(db):
    seed_event(db)
    payment = payments.create_payment(db, EVENT_ID, payment_payload(), USER_A)

    for action in (
        lambda: payments.confirm_payment(db, payment["id"], USER_A),
        lambda: payments.reject_payment(db, payment["id"], USER_A),
    ):
        try:
            action()
        except Exception as exc:
            assert_status(exc, 403)
        else:
            raise AssertionError("Expected sender payment resolution to fail")


def test_list_payments_returns_paginated_active_page(db):
    seed_event(db)
    base_time = datetime(2026, 1, 1, tzinfo=UTC)
    db.payments.insert_many(
        [
            {
                "id": f"cccccccc-cccc-cccc-cccc-ccccccccccc{index}",
                "event_id": EVENT_ID,
                "sender_id": USER_A,
                "receiver_id": USER_B,
                "amount_kopecks": 1000,
                "confirmed": False,
                "created_at": base_time + timedelta(days=index),
            }
            for index in range(3)
        ]
    )
    db.payments.insert_one(
        {
            "id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
            "event_id": EVENT_ID,
            "sender_id": USER_A,
            "receiver_id": USER_B,
            "amount_kopecks": 1000,
            "confirmed": False,
            "created_at": base_time + timedelta(days=4),
            "deleted_at": base_time + timedelta(days=5),
        }
    )

    page = payments.list_payments_by_event(db, EVENT_ID, USER_A, limit=2, offset=1)

    assert [payment["id"] for payment in page["items"]] == [
        "cccccccc-cccc-cccc-cccc-ccccccccccc1",
        "cccccccc-cccc-cccc-cccc-ccccccccccc0",
    ]
    assert page["limit"] == 2
    assert page["offset"] == 1
    assert page["total"] == 3


def test_payment_sender_must_match_authenticated_user(db):
    seed_event(db)

    try:
        payments.create_payment(db, EVENT_ID, payment_payload(), USER_B)
    except Exception as exc:
        assert_status(exc, 403)
    else:
        raise AssertionError("Expected payment creation for another sender to fail")


def test_only_payment_receiver_can_confirm(db):
    seed_event(db)
    payment = payments.create_payment(db, EVENT_ID, payment_payload(), USER_A)

    try:
        payments.update_payment(db, payment["id"], schemas.PaymentUpdate(confirmed=True), USER_A)
    except Exception as exc:
        assert_status(exc, 403)
    else:
        raise AssertionError("Expected sender confirmation to fail")


def test_unconfirmed_payment_can_be_deleted_by_sender_or_receiver(db):
    seed_event(db)
    payment = payments.create_payment(db, EVENT_ID, payment_payload(), USER_A)

    payments.delete_payment(db, payment["id"], USER_A)

    stored = db.payments.find_one({"id": payment["id"]})
    assert stored["deleted_at"] is not None
    assert payments.list_payments_by_event(db, EVENT_ID, USER_A, limit=50, offset=0)["items"] == []
    assert db.audit_events.find_one({"action": "payment.deleted", "resource_id": payment["id"]})


def test_confirmed_payment_cannot_be_deleted(db):
    seed_event(db)
    payment = payments.create_payment(db, EVENT_ID, payment_payload(), USER_A)
    payments.update_payment(db, payment["id"], schemas.PaymentUpdate(confirmed=True), USER_B)

    try:
        payments.delete_payment(db, payment["id"], USER_B)
    except Exception as exc:
        assert_status(exc, 409)
    else:
        raise AssertionError("Expected confirmed payment delete to fail")


def test_confirmed_payment_cannot_be_unconfirmed(db):
    seed_event(db)
    payment = payments.create_payment(db, EVENT_ID, payment_payload(), USER_A)
    payments.update_payment(db, payment["id"], schemas.PaymentUpdate(confirmed=True), USER_B)

    try:
        payments.update_payment(db, payment["id"], schemas.PaymentUpdate(confirmed=False), USER_B)
    except Exception as exc:
        assert_status(exc, 409)
    else:
        raise AssertionError("Expected confirmed payment unconfirm to fail")


def test_receipt_delete_soft_deletes_and_hides_from_reads(db):
    seed_event(db)
    receipt = receipts.create_receipt(db, EVENT_ID, receipt_payload(), USER_A)

    receipts.delete_receipt(db, receipt["id"], USER_A)

    stored = db.receipts.find_one({"id": receipt["id"]})
    assert stored["deleted_at"] is not None
    assert receipts.list_receipts_by_event(db, EVENT_ID, USER_A, limit=50, offset=0)["items"] == []
    assert db.audit_events.find_one({"action": "receipt.deleted", "resource_id": receipt["id"]})


def test_receipt_delete_requires_creator_or_payer(db):
    seed_event(db)
    receipt = receipts.create_receipt(db, EVENT_ID, receipt_payload(), USER_A)

    try:
        receipts.delete_receipt(db, receipt["id"], USER_B)
    except Exception as exc:
        assert_status(exc, 403)
    else:
        raise AssertionError("Expected non-payer member receipt delete to fail")

    assert "deleted_at" not in db.receipts.find_one({"id": receipt["id"]})


def test_confirmed_receipt_cannot_be_deleted(db):
    seed_event(db)
    receipt = receipts.create_receipt(db, EVENT_ID, receipt_payload(), USER_A)
    confirm_receipt_for_all(db, receipt["id"])

    try:
        receipts.delete_receipt(db, receipt["id"], USER_A)
    except Exception as exc:
        assert_status(exc, 409)
    else:
        raise AssertionError("Expected confirmed receipt delete to fail")

    assert "deleted_at" not in db.receipts.find_one({"id": receipt["id"]})
    assert balances.get_event_balances(db, EVENT_ID, USER_A)[0]["amount_kopecks"] == 5000


def test_receipt_image_write_requires_creator_or_payer(db, fake_s3, monkeypatch):
    monkeypatch.setenv("S3_BUCKET", "split-bucket")
    seed_event(db)
    receipt = receipts.create_receipt(db, EVENT_ID, receipt_payload(), USER_A)

    for action in (
        lambda: receipt_image.upload_receipt_image(
            db,
            fake_s3,
            receipt["id"],
            b"\xff\xd8\xffjpeg",
            "image/jpeg",
            USER_B,
        ),
        lambda: receipt_image.delete_receipt_image(db, fake_s3, receipt["id"], USER_B),
    ):
        try:
            action()
        except Exception as exc:
            assert_status(exc, 403)
        else:
            raise AssertionError("Expected non-payer member receipt image write to fail")

    assert "image_key" not in db.receipts.find_one({"id": receipt["id"]})
    assert fake_s3.objects == {}


def test_event_access_blocks_non_members(db):
    seed_event(db)

    try:
        receipts.list_receipts_by_event(db, EVENT_ID, USER_C, limit=50, offset=0)
    except Exception as exc:
        assert_status(exc, 403)
    else:
        raise AssertionError("Expected non-member access to fail")


def test_removed_event_member_loses_access(db):
    seed_event(db)

    events.remove_participant(db, EVENT_ID, USER_B, USER_A)

    membership = db.event_memberships.find_one({"event_id": EVENT_ID, "user_id": USER_B})
    assert membership["status"] == "removed"
    assert membership["removed_at"] is not None
    try:
        receipts.list_receipts_by_event(db, EVENT_ID, USER_B, limit=50, offset=0)
    except Exception as exc:
        assert_status(exc, 403)
    else:
        raise AssertionError("Expected removed event member access to fail")


def test_event_invite_preview_accept_and_duplicate_accept(db):
    seed_event(db)
    invite = events.create_event_invite(
        db,
        EVENT_ID,
        schemas.CreateEventInviteRequest(expires_in_seconds=3600),
        USER_A,
    )

    preview = events.preview_event_invite(db, invite["token"], USER_C)
    accepted = events.accept_event_invite(db, invite["token"], USER_C)
    accepted_again = events.accept_event_invite(db, invite["token"], USER_C)

    assert preview["event_id"] == EVENT_ID
    assert preview["event_name"] == "Trip"
    assert preview["creator_id"] == USER_A
    assert preview["participant_count"] == 2
    assert preview["expires_at"].date() == invite["expires_at"].date()
    assert any(
        item["user_id"] == USER_C and item["role"] == "member" for item in accepted["participants"]
    )
    assert (
        len(
            [
                membership
                for membership in db.event_memberships.find(
                    {"event_id": EVENT_ID, "user_id": USER_C}
                )
            ]
        )
        == 1
    )
    assert any(item["user_id"] == USER_C for item in accepted_again["participants"])


def test_event_invite_decline_records_decision_without_membership(db):
    seed_event(db)
    invite = events.create_event_invite(
        db,
        EVENT_ID,
        schemas.CreateEventInviteRequest(expires_in_seconds=3600),
        USER_A,
    )

    declined = events.decline_event_invite(db, invite["token"], USER_C)
    preview = events.preview_event_invite(db, invite["token"], USER_C)

    assert declined["actor_decision"] == "declined"
    assert preview["actor_decision"] == "declined"
    assert db.event_memberships.count_documents({"event_id": EVENT_ID, "user_id": USER_C}) == 0
    assert db.audit_events.find_one({"action": "invite.declined", "resource_id": invite["id"]})


def test_event_invite_revoke_blocks_accept(db):
    seed_event(db)
    invite = events.create_event_invite(
        db,
        EVENT_ID,
        schemas.CreateEventInviteRequest(expires_in_seconds=3600),
        USER_A,
    )

    events.revoke_event_invite(db, EVENT_ID, invite["id"], USER_A)

    try:
        events.accept_event_invite(db, invite["token"], USER_C)
    except Exception as exc:
        assert_status(exc, 410)
    else:
        raise AssertionError("Expected revoked invite accept to fail")


def test_event_invite_expiry_blocks_preview(db):
    seed_event(db)
    invite = events.create_event_invite(
        db,
        EVENT_ID,
        schemas.CreateEventInviteRequest(expires_in_seconds=3600),
        USER_A,
    )
    db.event_invites.update_one(
        {"id": invite["id"]},
        {"$set": {"expires_at": datetime(2025, 1, 1, tzinfo=UTC)}},
    )

    try:
        events.preview_event_invite(db, invite["token"], USER_C)
    except Exception as exc:
        assert_status(exc, 410)
    else:
        raise AssertionError("Expected expired invite preview to fail")


def test_only_event_creator_can_create_or_revoke_invites(db):
    seed_event(db)

    try:
        events.create_event_invite(
            db,
            EVENT_ID,
            schemas.CreateEventInviteRequest(expires_in_seconds=3600),
            USER_B,
        )
    except Exception as exc:
        assert_status(exc, 403)
    else:
        raise AssertionError("Expected non-creator invite creation to fail")

    invite = events.create_event_invite(
        db,
        EVENT_ID,
        schemas.CreateEventInviteRequest(expires_in_seconds=3600),
        USER_A,
    )
    try:
        events.revoke_event_invite(db, EVENT_ID, invite["id"], USER_B)
    except Exception as exc:
        assert_status(exc, 403)
    else:
        raise AssertionError("Expected non-creator invite revoke to fail")


def test_closed_event_blocks_mutations_but_allows_reads(db):
    seed_event(db, is_closed=True)

    assert receipts.list_receipts_by_event(db, EVENT_ID, USER_A, limit=50, offset=0)["items"] == []

    for action in (
        lambda: receipts.create_receipt(db, EVENT_ID, receipt_payload(), USER_A),
        lambda: payments.create_payment(db, EVENT_ID, payment_payload(), USER_A),
        lambda: events.add_participants(
            db,
            EVENT_ID,
            schemas.AddParticipantsRequest(user_ids=[USER_C]),
            USER_A,
        ),
    ):
        try:
            action()
        except Exception as exc:
            assert_status(exc, 409)
        else:
            raise AssertionError("Expected closed event mutation to fail")


def test_only_event_creator_can_close_or_reopen_event(db):
    seed_event(db)

    try:
        events.update_event(db, EVENT_ID, schemas.EventUpdate(is_closed=True), USER_B)
    except Exception as exc:
        assert_status(exc, 403)
    else:
        raise AssertionError("Expected non-creator close to fail")

    updated = events.update_event(db, EVENT_ID, schemas.EventUpdate(is_closed=True), USER_A)

    assert updated["is_closed"] is True


def test_only_event_creator_can_rename_event(db):
    seed_event(db)

    try:
        events.update_event(db, EVENT_ID, schemas.EventUpdate(name="New name"), USER_B)
    except Exception as exc:
        assert_status(exc, 403)
    else:
        raise AssertionError("Expected non-creator rename to fail")


def test_only_event_creator_can_manage_participants(db):
    seed_event(db)

    for action in (
        lambda: events.add_participants(
            db,
            EVENT_ID,
            schemas.AddParticipantsRequest(user_ids=[USER_C]),
            USER_B,
        ),
        lambda: events.remove_participant(db, EVENT_ID, USER_A, USER_B),
    ):
        try:
            action()
        except Exception as exc:
            assert_status(exc, 403)
        else:
            raise AssertionError("Expected non-creator participant management to fail")


def test_event_delete_requires_transaction_support(db):
    seed_event(db)

    try:
        events.delete_event(db, EVENT_ID, USER_A)
    except Exception as exc:
        assert_status(exc, 503)
    else:
        raise AssertionError("Expected unsupported test transaction to fail")

    assert db.events.find_one({"id": EVENT_ID}) is not None


def test_client_report_sanitizes_sensitive_metadata_and_stores_actor(db):
    report = client_reports.create_client_report(
        db,
        schemas.ClientReportCreate(
            kind="automatic_error",
            severity="error",
            screen="events",
            message="Синхронизация не удалась",
            user_description="Нажал создать событие и увидел ошибку.",
            request_id="req-123",
            client_trace_id="trace-123",
            app_version="web-2026-07-07",
            url_path="/app#events",
            user_agent="Mozilla/5.0",
            online=True,
            metadata={
                "api_status": 500,
                "api_path": "/api/events",
                "component": "EventsView",
                "error_message": "Splitik LLM request failed.",
                "Authorization": "Bearer secret",
                "access_token": "secret",
                "raw_response": {"detail": "database password leaked"},
            },
        ),
        actor_user_id=USER_A,
        client_ip="127.0.0.1",
    )

    stored = db.client_feedback_reports.find_one({"id": report["id"]})

    assert report["actor_user_id"] == USER_A
    assert report["status"] == "new"
    assert stored["metadata"] == {
        "api_status": 500,
        "api_path": "/api/events",
        "component": "EventsView",
        "error_message": "Splitik LLM request failed.",
    }
    assert "Bearer secret" not in str(stored)
    assert "database password leaked" not in str(stored)


def test_client_report_supports_manual_guest_feedback_without_contact_leak(db):
    report = client_reports.create_client_report(
        db,
        schemas.ClientReportCreate(
            kind="manual_feedback",
            severity="warning",
            screen="profile",
            message="Пользователь отправил отзыв",
            user_description="Не понимаю, где добавить чек.",
            contact_allowed=False,
            contact="alice@example.com",
            metadata={"screen_label": "Профиль"},
        ),
        actor_user_id=None,
        client_ip="203.0.113.10",
    )

    stored = db.client_feedback_reports.find_one({"id": report["id"]})

    assert stored["actor_user_id"] is None
    assert stored["contact_allowed"] is False
    assert stored["contact"] is None
    assert stored["client_ip"] == "203.0.113.10"


def test_refresh_token_rotation_issues_new_pair(db):
    from tests.conftest import seed_users

    seed_users(db)
    raw = auth._issue_refresh_token(db, USER_A)

    response = auth.rotate_refresh_token(db, raw)

    assert response["token_type"] == "bearer"
    assert response["expires_in"] == int(tokens.access_token_ttl().total_seconds())
    assert db.refresh_tokens.count_documents({"user_id": USER_A}) == 2
    assert db.refresh_tokens.find_one({"token_hash": tokens.hash_refresh_token(raw)})["used_at"]


def test_refresh_token_can_retry_within_grace(db):
    from tests.conftest import seed_users

    seed_users(db)
    raw = auth._issue_refresh_token(db, USER_A)

    first = auth.rotate_refresh_token(db, raw)
    second = auth.rotate_refresh_token(db, raw)

    assert (
        first["access_token"] != second["access_token"]
        or first["refresh_token"] != second["refresh_token"]
    )


def test_refresh_token_retry_after_grace_fails(db):
    from datetime import timedelta
    from tests.conftest import seed_users

    seed_users(db)
    raw = auth._issue_refresh_token(db, USER_A)
    auth.rotate_refresh_token(db, raw)
    db.refresh_tokens.update_one(
        {"token_hash": tokens.hash_refresh_token(raw)},
        {"$set": {"used_at": auth.utc_now() - timedelta(seconds=121)}},
    )

    try:
        auth.rotate_refresh_token(db, raw)
    except Exception as exc:
        assert_status(exc, 401)
    else:
        raise AssertionError("Expected refresh reuse after grace to fail")
