"""Persistence for users. Every statement goes through db.get_connection()."""

import db


class UserRepo:
    def insert(self, name: str) -> int:
        conn = db.get_connection()
        cur = conn.execute("INSERT INTO users (name) VALUES (?)", (name,))
        conn.commit()
        return int(cur.lastrowid)

    def fetch_all(self) -> list[dict]:
        conn = db.get_connection()
        rows = conn.execute("SELECT id, name FROM users ORDER BY id").fetchall()
        return [{"id": r["id"], "name": r["name"]} for r in rows]

    def fetch_one(self, user_id: int) -> dict | None:
        conn = db.get_connection()
        row = conn.execute("SELECT id, name FROM users WHERE id = ?", (user_id,)).fetchone()
        return {"id": row["id"], "name": row["name"]} if row else None
