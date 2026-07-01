from datetime import UTC, datetime, timedelta
from uuid import UUID

from app import schemas
from app.core import tokens
from app.services import (
    audit,
    auth,
    balances,
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

    try:
        events.update_event(db, EVENT_ID, schemas.EventUpdate(debt_display_mode="bad"), USER_A)
    except Exception as exc:
        assert_status(exc, 400)
    else:
        raise AssertionError("Expected invalid event policy to fail")


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

    assert upload["image_url"].endswith(stored["image_key"])
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

    try:
        disputes.create_dispute(
            db,
            schemas.DisputeCreate(
                resource_type="unknown",
                resource_id=receipt["id"],
                reason="Wrong split",
            ),
            USER_A,
        )
    except Exception as exc:
        assert_status(exc, 400)
    else:
        raise AssertionError("Expected invalid dispute resource type to fail")


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


def test_nearby_invite_code_preview_accept_and_duplicate_accept(db):
    seed_event(db)
    code = events.create_nearby_invite_code(
        db,
        EVENT_ID,
        schemas.CreateNearbyInviteCodeRequest(expires_in_seconds=180),
        USER_A,
    )

    preview = events.preview_nearby_invite_code(db, code["code"], USER_C)
    accepted = events.accept_nearby_invite_code(db, code["code"], USER_C)
    accepted_again = events.accept_nearby_invite_code(db, code["code"], USER_C)

    assert len(code["code"]) == 6
    assert code["code"].isdigit()
    assert preview["event_id"] == EVENT_ID
    assert any(item["user_id"] == USER_C for item in accepted["participants"])
    assert any(item["user_id"] == USER_C for item in accepted_again["participants"])
    assert db.event_memberships.count_documents({"event_id": EVENT_ID, "user_id": USER_C}) == 1


def test_nearby_invite_code_decline_records_decision_without_membership(db):
    seed_event(db)
    code = events.create_nearby_invite_code(
        db,
        EVENT_ID,
        schemas.CreateNearbyInviteCodeRequest(expires_in_seconds=180),
        USER_A,
    )

    declined = events.decline_nearby_invite_code(db, code["code"], USER_C)
    preview = events.preview_nearby_invite_code(db, code["code"], USER_C)

    assert declined["actor_decision"] == "declined"
    assert preview["actor_decision"] == "declined"
    assert db.event_memberships.count_documents({"event_id": EVENT_ID, "user_id": USER_C}) == 0


def test_nearby_invite_code_expiry_blocks_accept(db):
    seed_event(db)
    code = events.create_nearby_invite_code(
        db,
        EVENT_ID,
        schemas.CreateNearbyInviteCodeRequest(expires_in_seconds=180),
        USER_A,
    )
    db.nearby_invite_codes.update_one(
        {"id": code["id"]},
        {"$set": {"expires_at": datetime(2025, 1, 1, tzinfo=UTC)}},
    )

    try:
        events.accept_nearby_invite_code(db, code["code"], USER_C)
    except Exception as exc:
        assert_status(exc, 410)
    else:
        raise AssertionError("Expected expired nearby code accept to fail")


def test_only_event_creator_can_create_nearby_invite_code(db):
    seed_event(db)

    try:
        events.create_nearby_invite_code(
            db,
            EVENT_ID,
            schemas.CreateNearbyInviteCodeRequest(expires_in_seconds=180),
            USER_B,
        )
    except Exception as exc:
        assert_status(exc, 403)
    else:
        raise AssertionError("Expected non-creator nearby code creation to fail")


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
