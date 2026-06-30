#!/usr/bin/env python3
import argparse
from datetime import UTC, datetime
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pymongo import MongoClient  # noqa: E402

from app.core.db import build_mongodb_uri, load_env_file  # noqa: E402


DEMO_USERS = [
    ("Анна Смирнова", "+79001000001", "anna.demo@example.com", "anna_demo"),
    ("Дима Волков", "+79001000002", "dima.demo@example.com", "dima_demo"),
    ("Катя Орлова", "+79001000003", "katya.demo@example.com", "katya_demo"),
    ("Максим Соколов", "+79001000004", "maxim.demo@example.com", "maxim_demo"),
    ("Лена Морозова", "+79001000005", "lena.demo@example.com", "lena_demo"),
    ("Павел Иванов", "+79001000006", "pavel.demo@example.com", "pavel_demo"),
]


def _now() -> datetime:
    return datetime.now(UTC)


def _new_uuid() -> str:
    return str(uuid4())


def _search_name(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def _pair_key(user_a: str, user_b: str) -> str:
    return ":".join(sorted([user_a, user_b]))


def _find_target_user(db, user_name: str):
    normalized = _search_name(user_name)
    return db.users.find_one(
        {
            "$or": [
                {"search_name": normalized},
                {"name": {"$regex": f"^{user_name}$", "$options": "i"}},
                {"public_handle": {"$in": ["ilya_karsakov", "ilya"]}},
                {"email": {"$in": ["ilya@example.com", "ilya.karsakov@example.com"]}},
            ]
        }
    )


def _upsert_demo_user(db, name: str, phone: str, email: str, handle: str) -> str:
    now = _now()
    existing = db.users.find_one({"public_handle": handle})
    fields = {
        "name": name,
        "phone_number": phone,
        "email": email,
        "public_handle": handle,
        "discovery_enabled": True,
        "payment_phone": phone,
        "payment_phone_visibility": "friends",
        "phone_verified": False,
        "search_name": _search_name(name),
        "updated_at": now,
    }
    if existing:
        db.users.update_one({"id": existing["id"]}, {"$set": fields})
        return existing["id"]

    user_id = _new_uuid()
    db.users.insert_one({"id": user_id, **fields, "created_at": now})
    return user_id


def _upsert_friendship(db, target_user_id: str, friend_user_id: str) -> None:
    now = _now()
    pair_key = _pair_key(target_user_id, friend_user_id)
    existing = db.friends.find_one({"pair_key": pair_key, "deleted_at": {"$exists": False}})
    fields = {
        "requester_id": target_user_id,
        "addressee_id": friend_user_id,
        "status": "accepted",
        "accepted_at": now,
        "updated_at": now,
    }
    if existing:
        db.friends.update_one({"id": existing["id"]}, {"$set": fields})
        return

    db.friends.insert_one(
        {
            "id": _new_uuid(),
            "pair_key": pair_key,
            **fields,
            "created_at": now,
        }
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed demo friends for a SplitApp user.")
    parser.add_argument("--user-name", default="Илья Карсаков")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--confirm-local", action="store_true")
    parser.add_argument("--confirm-server", action="store_true")
    args = parser.parse_args()

    if args.confirm_local == args.confirm_server:
        parser.error("Pass exactly one of --confirm-local or --confirm-server.")

    load_env_file(args.env_file)
    client = MongoClient(build_mongodb_uri(), serverSelectionTimeoutMS=5000)
    db_name = __import__("os").getenv("MONGODB_DB_NAME", "splitapp")
    db = client[db_name]

    target = _find_target_user(db, args.user_name)
    if not target:
        print(f"User not found: {args.user_name}", file=sys.stderr)
        return 1

    created_or_updated = 0
    for name, phone, email, handle in DEMO_USERS:
        friend_id = _upsert_demo_user(db, name, phone, email, handle)
        _upsert_friendship(db, target["id"], friend_id)
        created_or_updated += 1

    print(f"Seeded {created_or_updated} demo friends for {target['name']}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
