from datetime import UTC

from app import schemas
from app.core import tokens
from app.services import auth, events, payments, receipt_image, receipts, users

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
    assert created["users"] == [USER_A]
    assert [event["id"] for event in events.list_events(db, USER_A)] == [created["id"]]


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


def test_receipt_create_validates_total_and_membership(db):
    seed_event(db)

    receipt = receipts.create_receipt(db, EVENT_ID, receipt_payload(), USER_A)

    assert receipt["event_id"] == EVENT_ID
    assert receipt["payer_id"] == USER_A
    assert receipt["total_amount"] == 100
    assert len(receipt["items"]) == 1

    fetched = receipts.get_receipt(db, receipt["id"], USER_B)
    assert fetched["id"] == receipt["id"]
    assert "share_items" not in fetched


def test_receipt_detail_requires_event_membership(db):
    seed_event(db)
    receipt = receipts.create_receipt(db, EVENT_ID, receipt_payload(), USER_A)

    try:
        receipts.get_receipt(db, receipt["id"], USER_C)
    except Exception as exc:
        assert_status(exc, 403)
    else:
        raise AssertionError("Expected non-member receipt detail access to fail")


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

    receipt_image.delete_receipt_image(db, fake_s3, receipt["id"], USER_A)
    after_delete = db.receipts.find_one({"id": receipt["id"]})

    assert upload["image_url"].endswith(stored["image_key"])
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

    assert db.payments.find_one({"id": payment["id"]}) is None


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


def test_event_access_blocks_non_members(db):
    seed_event(db)

    try:
        receipts.list_receipts_by_event(db, EVENT_ID, USER_C)
    except Exception as exc:
        assert_status(exc, 403)
    else:
        raise AssertionError("Expected non-member access to fail")


def test_closed_event_blocks_mutations_but_allows_reads(db):
    seed_event(db, is_closed=True)

    assert receipts.list_receipts_by_event(db, EVENT_ID, USER_A) == []

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
