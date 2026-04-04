from pymongo.database import Database


def ensure_indexes(db: Database) -> None:
    db.users.create_index("id", unique=True)
    db.users.create_index("phone_number", unique=True)
    db.users.create_index("yandex_id", unique=True, sparse=True)
    db.refresh_tokens.create_index("token_hash", unique=True)
    db.refresh_tokens.create_index("expires_at", expireAfterSeconds=0)
    db.events.create_index("id", unique=True)
    db.receipts.create_index("id", unique=True)
    db.receipts.create_index([("event_id", 1), ("created_at", -1)])
    db.payments.create_index("id", unique=True)
    db.payments.create_index([("event_id", 1), ("created_at", -1)])
