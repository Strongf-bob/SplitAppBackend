from pymongo.database import Database

from app.services.common import user_to_api_dict


def list_users(db: Database) -> list[dict]:
    return [user_to_api_dict(user) for user in db.users.find({}).sort("name", 1)]
