import importlib.util
from pathlib import Path

import pytest
from fastapi import HTTPException

from app import schemas
from app.services import splitik, splitik_llm
from tests.conftest import EVENT_ID, USER_A, USER_B, USER_C, seed_event, seed_users


def _mock_llm(monkeypatch):
    calls = []

    def fake_reply(*, system_prompt, user_message, context):
        calls.append(
            {
                "system_prompt": system_prompt,
                "user_message": user_message,
                "context": context,
            }
        )
        return "Сплитик: готово."

    monkeypatch.setattr(splitik_llm, "generate_splitik_reply", fake_reply)
    return calls


def test_splitik_event_context_requires_membership(db, monkeypatch):
    _mock_llm(monkeypatch)
    seed_event(db)

    with pytest.raises(HTTPException) as exc:
        splitik.send_splitik_message(
            db,
            schemas.SplitikMessageRequest(
                mode="event",
                message="Что по балансу?",
                entry_point=schemas.SplitikEntryPoint(type="event", event_id=EVENT_ID),
            ),
            USER_C,
        )

    assert exc.value.status_code == 403


def test_splitik_llm_is_mocked_and_receives_bounded_event_context(db, monkeypatch):
    calls = _mock_llm(monkeypatch)
    seed_event(db)

    response = splitik.send_splitik_message(
        db,
        schemas.SplitikMessageRequest(
            mode="event",
            message="Почему я должен?",
            entry_point=schemas.SplitikEntryPoint(type="event", event_id=EVENT_ID),
        ),
        USER_A,
    )

    assert response["assistant_message"] == "Сплитик: готово."
    assert response["context_chips"][0]["value"] == "Trip"
    assert "read:balance_explanation" in response["capabilities"]
    assert calls[0]["context"]["event"]["id"] == EVENT_ID
    assert {item["membership"]["user_id"] for item in calls[0]["context"]["participants"]} == {
        USER_A,
        USER_B,
    }


def test_splitik_draft_does_not_change_state_until_commit(db, monkeypatch):
    _mock_llm(monkeypatch)
    seed_users(db)

    response = splitik.send_splitik_message(
        db,
        schemas.SplitikMessageRequest(
            mode="general",
            message="Создай событие: Ужин в Duo",
        ),
        USER_A,
    )

    assert len(response["drafts"]) == 1
    assert db.events.count_documents({"name": "Ужин в Duo"}) == 0

    committed = splitik.commit_splitik_draft(db, response["drafts"][0]["id"], USER_A)

    assert committed["draft"]["status"] == "committed"
    assert committed["resource"]["name"] == "Ужин в Duo"
    assert db.events.count_documents({"name": "Ужин в Duo"}) == 1


def test_splitik_rejects_foreign_draft_commit(db, monkeypatch):
    _mock_llm(monkeypatch)
    seed_users(db)
    response = splitik.send_splitik_message(
        db,
        schemas.SplitikMessageRequest(mode="general", message="Создай событие: Поездка"),
        USER_A,
    )

    with pytest.raises(HTTPException) as exc:
        splitik.commit_splitik_draft(db, response["drafts"][0]["id"], USER_B)

    assert exc.value.status_code == 404


def test_seed_demo_friends_is_idempotent(db, monkeypatch):
    seed_users(db)
    db.users.update_one(
        {"id": USER_A},
        {
            "$set": {
                "name": "Илья Карсаков",
                "search_name": "илья карсаков",
                "public_handle": "ilya_karsakov",
            }
        },
    )
    module_path = Path(__file__).resolve().parents[1] / "tools" / "seed_demo_friends.py"
    spec = importlib.util.spec_from_file_location("seed_demo_friends", module_path)
    seed_demo_friends = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(seed_demo_friends)

    class FakeClient:
        def __getitem__(self, name):
            return db

    monkeypatch.setattr(seed_demo_friends, "MongoClient", lambda *args, **kwargs: FakeClient())
    monkeypatch.setattr(seed_demo_friends, "build_mongodb_uri", lambda: "mongodb://unused")
    monkeypatch.setattr(
        "sys.argv",
        ["seed_demo_friends.py", "--user-name", "Илья Карсаков", "--confirm-local"],
    )

    assert seed_demo_friends.main() == 0
    assert seed_demo_friends.main() == 0
    assert db.users.count_documents({"public_handle": {"$regex": "_demo$"}}) == 6
    assert db.friends.count_documents({"requester_id": USER_A, "status": "accepted"}) == 6
