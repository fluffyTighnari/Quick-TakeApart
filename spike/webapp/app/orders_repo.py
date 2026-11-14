"""Order persistence."""

import db


class OrderRepo:
    def insert(self, user_id: int, total: float) -> int:
        conn = db.get_connection()
        cur = conn.execute("INSERT INTO orders (user_id, total) VALUES (?, ?)", (user_id, total))
        conn.commit()
        return int(cur.lastrowid)

    def fetch_all(self) -> list[dict]:
        conn = db.get_connection()
        rows = conn.execute("SELECT id, user_id, total FROM orders ORDER BY id").fetchall()
        return [{"id": r["id"], "user_id": r["user_id"], "total": r["total"]} for r in rows]

    def total_for_user(self, user_id: int) -> float:
        conn = db.get_connection()
        row = conn.execute("SELECT COALESCE(SUM(total), 0) AS s FROM orders WHERE user_id = ?",
                           (user_id,)).fetchone()
        return float(row["s"])
