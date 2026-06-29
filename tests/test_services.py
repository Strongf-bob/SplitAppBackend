from datetime import UTC, datetime, timedelta

from app import schemas
from app.core import tokens
from app.services import auth, balances, events, payments, receipt_image, receipts, users

from tests.conftest import (
    EVENT_ID,
    USER_A,
    USER_B,
    USER_C,
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
    assert [(item["user_id"], item["role"], item["status"]) for item in created["participants"]] == [
        (USER_A, "creator", "active")
    ]
    page = events.list_events(db, USER_A, limit=50, offset=0)

    assert [event["id"] for event in page["items"]] == [created["id"]]
    assert page["total"] == 1


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
    assert receipt["total_amount_kopecks"] == 10000
    assert len(receipt["items"]) == 1
    stored = db.receipts.find_one({"id": receipt["id"]})
    assert stored["total_amount_kopecks"] == 10000
    assert isinstance(stored["total_amount_kopecks"], int)

    fetched = receipts.get_receipt(db, receipt["id"], USER_B)
    assert fetched["id"] == receipt["id"]
    assert "share_items" not in fetched


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
    receipts.create_receipt(db, EVENT_ID, payload, USER_A)

    rows = balances.get_event_balances(db, EVENT_ID, USER_A)

    assert rows == [
        {
            "event_id": EVENT_ID,
            "debitor_id": USER_B,
            "creditor_id": USER_A,
            "amount_kopecks": 30,
        }
    ]


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
    assert any(item["user_id"] == USER_C and item["role"] == "member" for item in accepted["participants"])
    assert len(
        [
            membership
            for membership in db.event_memberships.find({"event_id": EVENT_ID, "user_id": USER_C})
        ]
    ) == 1
    assert any(item["user_id"] == USER_C for item in accepted_again["participants"])


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

    assert first["access_token"] != second["access_token"] or first["refresh_token"] != second["refresh_token"]


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
