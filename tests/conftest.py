from datetime import UTC, datetime

import mongomock
import pytest


USER_A = "11111111-1111-1111-1111-111111111111"
USER_B = "22222222-2222-2222-2222-222222222222"
USER_C = "33333333-3333-3333-3333-333333333333"
EVENT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
RECEIPT_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
PAYMENT_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.delenv("JWT_REFRESH_REUSE_GRACE_SECONDS", raising=False)


@pytest.fixture
def db():
    client = mongomock.MongoClient()
    return client.splitapp_test


@pytest.fixture
def fake_s3():
    class FakeS3:
        def __init__(self):
            self.objects = {}
            self.deleted = []

        def put_object(self, **kwargs):
            self.objects[(kwargs["Bucket"], kwargs["Key"])] = kwargs

        def delete_object(self, **kwargs):
            self.deleted.append((kwargs["Bucket"], kwargs["Key"]))
            self.objects.pop((kwargs["Bucket"], kwargs["Key"]), None)

        def generate_presigned_url(self, operation, Params, ExpiresIn):
            return f"https://signed.example/{Params['Bucket']}/{Params['Key']}?expires={ExpiresIn}"

    return FakeS3()


def seed_users(db) -> None:
    db.users.insert_many(
        [
            {
                "id": USER_A,
                "name": "Alice",
                "phone_number": "+10000000001",
                "email": "alice@example.com",
                "created_at": datetime(2026, 1, 1, tzinfo=UTC),
                "updated_at": datetime(2026, 1, 1, tzinfo=UTC),
            },
            {
                "id": USER_B,
                "name": "Bob",
                "phone_number": "+10000000002",
                "email": "bob@example.com",
                "created_at": datetime(2026, 1, 1, tzinfo=UTC),
                "updated_at": datetime(2026, 1, 1, tzinfo=UTC),
            },
            {
                "id": USER_C,
                "name": "Cara",
                "phone_number": "+10000000003",
                "email": "cara@example.com",
                "created_at": datetime(2026, 1, 1, tzinfo=UTC),
                "updated_at": datetime(2026, 1, 1, tzinfo=UTC),
            },
        ]
    )


def seed_event(db, *, is_closed: bool = False) -> None:
    seed_users(db)
    db.events.insert_one(
        {
            "id": EVENT_ID,
            "creator_id": USER_A,
            "name": "Trip",
            "is_closed": is_closed,
            "users": [USER_A, USER_B],
            "created_at": datetime(2026, 1, 1, tzinfo=UTC),
            "updated_at": datetime(2026, 1, 1, tzinfo=UTC),
        }
    )


def receipt_payload():
    from app import schemas

    return schemas.CreateReceiptRequest(
        payer_id=USER_A,
        title="Dinner",
        total_amount=100,
        items=[
            schemas.CreateReceiptItemRequest(
                name="Meal",
                cost=100,
                share_items=[
                    schemas.CreateShareItemRequest(user_id=USER_A, share_value=0.5),
                    schemas.CreateShareItemRequest(user_id=USER_B, share_value=0.5),
                ],
            )
        ],
    )


def payment_payload():
    from app import schemas

    return schemas.PaymentCreate(sender_id=USER_A, receiver_id=USER_B, amount=50)
