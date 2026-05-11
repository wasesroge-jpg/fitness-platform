"""SQLite database layer for the fitness platform."""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Iterator

DB_PATH = os.environ.get(
    "FITNESS_DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.db"),
)


SCHEMA = """
CREATE TABLE IF NOT EXISTS workouts (
    id INTEGER PRIMARY KEY,
    polar_id TEXT UNIQUE,
    date TEXT,
    sport TEXT,
    distance_km REAL,
    duration_min INTEGER,
    avg_hr INTEGER,
    max_hr INTEGER,
    calories INTEGER,
    load_score REAL,
    start_time TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS recovery (
    id INTEGER PRIMARY KEY,
    date TEXT UNIQUE,
    nightly_recharge REAL,
    hrv_ms REAL,
    resting_hr INTEGER,
    sleep_duration_min INTEGER,
    sleep_score INTEGER,
    deep_sleep_min INTEGER,
    light_sleep_min INTEGER,
    rem_sleep_min INTEGER
);

CREATE TABLE IF NOT EXISTS nutrition_log (
    id INTEGER PRIMARY KEY,
    date TEXT,
    meal_name TEXT,
    kcal INTEGER,
    protein_g REAL,
    fat_g REAL,
    carbs_g REAL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY,
    name TEXT,
    kcal_per_100g INTEGER,
    protein_g REAL,
    fat_g REAL,
    carbs_g REAL
);

CREATE TABLE IF NOT EXISTS weight_log (
    id INTEGER PRIMARY KEY,
    date TEXT,
    weight_kg REAL
);

CREATE TABLE IF NOT EXISTS day_notes (
    id INTEGER PRIMARY KEY,
    date TEXT UNIQUE,
    note TEXT,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS nutrition_goals (
    id INTEGER PRIMARY KEY,
    kcal INTEGER DEFAULT 2400,
    protein_g INTEGER DEFAULT 200,
    fat_g INTEGER DEFAULT 90,
    carbs_g INTEGER DEFAULT 260
);
"""


def _row_factory(cursor: sqlite3.Cursor, row: tuple) -> dict:
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = _row_factory
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        existing = conn.execute("SELECT id FROM nutrition_goals WHERE id = 1").fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO nutrition_goals (id, kcal, protein_g, fat_g, carbs_g) "
                "VALUES (1, 2400, 200, 90, 260)"
            )


def is_empty() -> bool:
    with get_conn() as conn:
        n_workouts = conn.execute("SELECT COUNT(*) AS c FROM workouts").fetchone()["c"]
        n_recovery = conn.execute("SELECT COUNT(*) AS c FROM recovery").fetchone()["c"]
    return n_workouts == 0 and n_recovery == 0


# -------------------- workouts --------------------

def upsert_workout(workout: dict) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO workouts (polar_id, date, sport, distance_km, duration_min,
                                  avg_hr, max_hr, calories, load_score, start_time, notes)
            VALUES (:polar_id, :date, :sport, :distance_km, :duration_min,
                    :avg_hr, :max_hr, :calories, :load_score, :start_time, :notes)
            ON CONFLICT(polar_id) DO UPDATE SET
                date=excluded.date,
                sport=excluded.sport,
                distance_km=excluded.distance_km,
                duration_min=excluded.duration_min,
                avg_hr=excluded.avg_hr,
                max_hr=excluded.max_hr,
                calories=excluded.calories,
                load_score=excluded.load_score,
                start_time=excluded.start_time
            """,
            workout,
        )


def list_workouts(since: str | None = None, until: str | None = None) -> list[dict]:
    sql = "SELECT * FROM workouts WHERE 1=1"
    params: list[Any] = []
    if since:
        sql += " AND date >= ?"
        params.append(since)
    if until:
        sql += " AND date <= ?"
        params.append(until)
    sql += " ORDER BY date DESC, start_time DESC"
    with get_conn() as conn:
        return conn.execute(sql, params).fetchall()


def recent_workouts(limit: int = 5) -> list[dict]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM workouts ORDER BY date DESC, start_time DESC LIMIT ?",
            (limit,),
        ).fetchall()


def workouts_by_date(target: str) -> list[dict]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM workouts WHERE date = ? ORDER BY start_time", (target,)
        ).fetchall()


def training_load(days: int = 7) -> float:
    since = (date.today() - timedelta(days=days - 1)).isoformat()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(load_score), 0) AS total FROM workouts WHERE date >= ?",
            (since,),
        ).fetchone()
    return round(float(row["total"] or 0), 1)


def daily_load(days: int = 14) -> list[dict]:
    """Return list of {date, load} for last N days, oldest first, zero-filled."""
    today = date.today()
    rows = {}
    with get_conn() as conn:
        for r in conn.execute(
            "SELECT date, SUM(load_score) AS load FROM workouts "
            "WHERE date >= ? GROUP BY date",
            ((today - timedelta(days=days - 1)).isoformat(),),
        ).fetchall():
            rows[r["date"]] = round(float(r["load"] or 0), 1)
    return [
        {
            "date": (today - timedelta(days=days - 1 - i)).isoformat(),
            "load": rows.get((today - timedelta(days=days - 1 - i)).isoformat(), 0.0),
        }
        for i in range(days)
    ]


# -------------------- recovery --------------------

def upsert_recovery(rec: dict) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO recovery (date, nightly_recharge, hrv_ms, resting_hr,
                                  sleep_duration_min, sleep_score,
                                  deep_sleep_min, light_sleep_min, rem_sleep_min)
            VALUES (:date, :nightly_recharge, :hrv_ms, :resting_hr,
                    :sleep_duration_min, :sleep_score,
                    :deep_sleep_min, :light_sleep_min, :rem_sleep_min)
            ON CONFLICT(date) DO UPDATE SET
                nightly_recharge=excluded.nightly_recharge,
                hrv_ms=excluded.hrv_ms,
                resting_hr=excluded.resting_hr,
                sleep_duration_min=excluded.sleep_duration_min,
                sleep_score=excluded.sleep_score,
                deep_sleep_min=excluded.deep_sleep_min,
                light_sleep_min=excluded.light_sleep_min,
                rem_sleep_min=excluded.rem_sleep_min
            """,
            rec,
        )


def latest_recovery() -> dict | None:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM recovery ORDER BY date DESC LIMIT 1"
        ).fetchone()


def recovery_range(days: int = 14) -> list[dict]:
    today = date.today()
    since = (today - timedelta(days=days - 1)).isoformat()
    rows = {}
    with get_conn() as conn:
        for r in conn.execute(
            "SELECT * FROM recovery WHERE date >= ? ORDER BY date", (since,)
        ).fetchall():
            rows[r["date"]] = r
    out = []
    for i in range(days):
        d = (today - timedelta(days=days - 1 - i)).isoformat()
        r = rows.get(d)
        out.append(
            {
                "date": d,
                "nightly_recharge": r["nightly_recharge"] if r else None,
                "hrv_ms": r["hrv_ms"] if r else None,
                "resting_hr": r["resting_hr"] if r else None,
            }
        )
    return out


# -------------------- nutrition --------------------

def add_nutrition_entry(entry: dict) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO nutrition_log (date, meal_name, kcal, protein_g, fat_g, carbs_g)
            VALUES (:date, :meal_name, :kcal, :protein_g, :fat_g, :carbs_g)
            """,
            entry,
        )
        return int(cur.lastrowid)


def nutrition_for_date(target: str) -> list[dict]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM nutrition_log WHERE date = ? ORDER BY created_at",
            (target,),
        ).fetchall()


def nutrition_totals(target: str) -> dict:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT
                COALESCE(SUM(kcal), 0) AS kcal,
                COALESCE(SUM(protein_g), 0) AS protein_g,
                COALESCE(SUM(fat_g), 0) AS fat_g,
                COALESCE(SUM(carbs_g), 0) AS carbs_g
            FROM nutrition_log WHERE date = ?
            """,
            (target,),
        ).fetchone()
    return {
        "kcal": int(row["kcal"] or 0),
        "protein_g": round(float(row["protein_g"] or 0), 1),
        "fat_g": round(float(row["fat_g"] or 0), 1),
        "carbs_g": round(float(row["carbs_g"] or 0), 1),
    }


def get_goals() -> dict:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT kcal, protein_g, fat_g, carbs_g FROM nutrition_goals WHERE id = 1"
        ).fetchone()
    return row or {"kcal": 2400, "protein_g": 200, "fat_g": 90, "carbs_g": 260}


# -------------------- products --------------------

def list_products() -> list[dict]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM products ORDER BY name"
        ).fetchall()


def add_product(p: dict) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO products (name, kcal_per_100g, protein_g, fat_g, carbs_g)
            VALUES (:name, :kcal_per_100g, :protein_g, :fat_g, :carbs_g)
            """,
            p,
        )
        return int(cur.lastrowid)


# -------------------- weight --------------------

def add_weight(d: str, kg: float) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO weight_log (date, weight_kg) VALUES (?, ?)", (d, kg)
        )
        return int(cur.lastrowid)


def weight_range(days: int = 14) -> list[dict]:
    today = date.today()
    since = (today - timedelta(days=days - 1)).isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT date, AVG(weight_kg) AS weight_kg FROM weight_log "
            "WHERE date >= ? GROUP BY date ORDER BY date",
            (since,),
        ).fetchall()
    by_date = {r["date"]: round(float(r["weight_kg"]), 1) for r in rows}
    return [
        {
            "date": (today - timedelta(days=days - 1 - i)).isoformat(),
            "weight_kg": by_date.get(
                (today - timedelta(days=days - 1 - i)).isoformat()
            ),
        }
        for i in range(days)
    ]


# -------------------- notes --------------------

def get_note(d: str) -> str:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT note FROM day_notes WHERE date = ?", (d,)
        ).fetchone()
    return row["note"] if row else ""


def set_note(d: str, note: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO day_notes (date, note, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(date) DO UPDATE SET
                note=excluded.note,
                updated_at=CURRENT_TIMESTAMP
            """,
            (d, note),
        )
