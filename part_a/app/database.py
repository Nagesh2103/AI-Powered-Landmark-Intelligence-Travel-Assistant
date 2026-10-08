import sqlite3
from contextlib import contextmanager
from typing import Iterator, Optional

from .models import PlaceDetails, Review

DB_PATH = "landmarks.db"


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS places (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query TEXT NOT NULL,
                name TEXT NOT NULL,
                address TEXT,
                rating REAL,
                total_reviews INTEGER
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                place_id INTEGER NOT NULL,
                author TEXT,
                rating INTEGER,
                text TEXT,
                FOREIGN KEY(place_id) REFERENCES places(id)
            )
            """
        )


def save_place(place: PlaceDetails) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO places (query, name, address, rating, total_reviews) VALUES (?, ?, ?, ?, ?)",
            (place.source_query, place.name, place.address, place.rating, place.total_reviews),
        )
        place_id = cur.lastrowid
        for r in place.reviews:
            conn.execute(
                "INSERT INTO reviews (place_id, author, rating, text) VALUES (?, ?, ?, ?)",
                (place_id, r.author, r.rating, r.text),
            )
        return place_id


def get_cached_place(query: str) -> Optional[PlaceDetails]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM places WHERE query = ? ORDER BY id DESC LIMIT 1", (query,)
        ).fetchone()
        if not row:
            return None
        review_rows = conn.execute(
            "SELECT author, rating, text FROM reviews WHERE place_id = ?", (row["id"],)
        ).fetchall()
        reviews = [Review(author=r["author"], rating=r["rating"], text=r["text"]) for r in review_rows]
        return PlaceDetails(
            name=row["name"],
            address=row["address"],
            rating=row["rating"],
            total_reviews=row["total_reviews"],
            reviews=reviews,
            source_query=row["query"],
        )
