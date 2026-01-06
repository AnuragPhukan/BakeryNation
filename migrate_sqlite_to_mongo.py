import os
import sqlite3


def load_dotenv(path=".env"):
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("'").strip('"')
            if key:
                os.environ[key] = value


def get_mongo_collection():
    uri = os.environ.get("MONGODB_URI", "").strip()
    if not uri:
        raise RuntimeError("MONGODB_URI is not set")
    db_name = os.environ.get("MONGODB_DB", "bakery").strip() or "bakery"
    collection_name = os.environ.get("MONGODB_MATERIALS_COLLECTION", "materials").strip() or "materials"
    try:
        from pymongo import MongoClient
    except ImportError as exc:
        raise RuntimeError("pymongo is required to run this migration") from exc
    client = MongoClient(uri)
    return client[db_name][collection_name]


def main():
    load_dotenv()
    db_path = os.environ.get("MATERIALS_DB_PATH", os.path.join("Context", "materials.sqlite"))
    if not os.path.exists(db_path):
        raise RuntimeError(f"SQLite DB not found at {db_path}")
    coll = get_mongo_collection()
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT name, unit, unit_cost, currency FROM materials").fetchall()
    for row in rows:
        doc = dict(row)
        coll.update_one({"name": doc["name"]}, {"$set": doc}, upsert=True)
    print(f"Migrated {len(rows)} materials to MongoDB.")


if __name__ == "__main__":
    main()
