from fastapi import HTTPException

from app.services import user_avatar


class FakeImageResponse:
    status_code = 200
    content = b"\xff\xd8\xffavatar"
    headers = {"content-type": "image/jpeg; charset=binary"}


def test_import_yandex_avatar_stores_valid_image(fake_s3, monkeypatch):
    monkeypatch.setenv("S3_BUCKET", "split-bucket")
    monkeypatch.setattr(user_avatar.httpx, "get", lambda *_a, **_kw: FakeImageResponse())

    key = user_avatar.import_yandex_avatar(
        fake_s3,
        user_id="user-1",
        yandex_avatar_url="https://avatars.yandex.net/a.jpg",
    )

    assert key == "users/user-1/avatar.jpg"
    assert fake_s3.objects[("split-bucket", key)]["ContentType"] == "image/jpeg"


def test_avatar_route_redirects_to_presigned_object(db, fake_s3, monkeypatch):
    monkeypatch.setenv("S3_BUCKET", "split-bucket")
    db.users.insert_one({"id": "user-1", "avatar_key": "users/user-1/avatar.jpg"})

    response = user_avatar.get_avatar_redirect(db, fake_s3, "user-1")

    assert response.status_code == 307
    assert response.headers["location"].startswith(
        "https://signed.example/split-bucket/users/user-1/avatar.jpg"
    )


def test_avatar_route_returns_not_found_without_stored_avatar(db, fake_s3, monkeypatch):
    monkeypatch.setenv("S3_BUCKET", "split-bucket")
    db.users.insert_one({"id": "user-1"})

    try:
        user_avatar.get_avatar_redirect(db, fake_s3, "user-1")
    except HTTPException as error:
        assert error.status_code == 404
    else:
        raise AssertionError("expected a missing avatar to return 404")
