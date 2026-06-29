from datetime import UTC

from app import schemas
from app.core import tokens
from app.services import auth, events, payments, receipts

from tests.conftest import (
    EVENT_ID,
    USER_A,
    USER_B,
    USER_C,
    payment_payload,
    receipt_payload,
    seed_event,
)


def test_event_create_and_list_for_actor(db):
    from tests.conftest import seed_users

    seed_users(db)
    created = events.create_event(db, schemas.EventCreate(name=" Weekend "), USER_A)

    assert created["name"] == "Weekend"
    assert created["creator_id"] == USER_A
    assert created["users"] == [USER_A]
    assert [event["id"] for event in events.list_events(db, USER_A)] == [created["id"]]


def test_receipt_create_validates_total_and_membership(db):
    seed_event(db)

    receipt = receipts.create_receipt(db, EVENT_ID, receipt_payload(), USER_A)

    assert receipt["event_id"] == EVENT_ID
    assert receipt["payer_id"] == USER_A
    assert receipt["total_amount"] == 100
    assert len(receipt["items"]) == 1


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


def test_event_access_blocks_non_members(db):
    seed_event(db)

    try:
        receipts.list_receipts_by_event(db, EVENT_ID, USER_C)
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 403
    else:
        raise AssertionError("Expected non-member access to fail")


def test_refresh_token_rotation_issues_new_pair(db):
    from tests.conftest import seed_users

    seed_users(db)
    raw = auth._issue_refresh_token(db, USER_A)

    response = auth.rotate_refresh_token(db, raw)

    assert response["token_type"] == "bearer"
    assert response["expires_in"] == int(tokens.access_token_ttl().total_seconds())
    assert db.refresh_tokens.count_documents({"user_id": USER_A}) == 1
    assert db.refresh_tokens.find_one({"user_id": USER_A})["expires_at"].tzinfo in (UTC, None)
