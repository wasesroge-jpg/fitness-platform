"""Deterministic realistic mock data covering the last 30 days."""
from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta

from . import database as db


SPORTS = [
    ("running", 8.0, 45, 152, 70),
    ("running", 12.0, 70, 148, 90),
    ("cycling", 28.0, 75, 138, 80),
    ("swimming", 1.5, 35, 132, 50),
    ("running", 6.0, 35, 145, 55),
]


PRODUCTS = [
    {"name": "Овсянка", "kcal_per_100g": 380, "protein_g": 12.0, "fat_g": 6.5, "carbs_g": 67.0},
    {"name": "Куриная грудка", "kcal_per_100g": 165, "protein_g": 31.0, "fat_g": 3.6, "carbs_g": 0.0},
    {"name": "Бананы", "kcal_per_100g": 89, "protein_g": 1.1, "fat_g": 0.3, "carbs_g": 23.0},
    {"name": "Греческий йогурт", "kcal_per_100g": 97, "protein_g": 10.0, "fat_g": 5.0, "carbs_g": 3.6},
    {"name": "Лосось", "kcal_per_100g": 208, "protein_g": 20.0, "fat_g": 13.0, "carbs_g": 0.0},
    {"name": "Рис басмати", "kcal_per_100g": 350, "protein_g": 7.5, "fat_g": 1.0, "carbs_g": 78.0},
    {"name": "Авокадо", "kcal_per_100g": 160, "protein_g": 2.0, "fat_g": 15.0, "carbs_g": 9.0},
    {"name": "Яйцо", "kcal_per_100g": 155, "protein_g": 13.0, "fat_g": 11.0, "carbs_g": 1.1},
]


MEALS = [
    ("Завтрак: овсянка с бананом", 420, 18.0, 9.0, 70.0),
    ("Обед: курица + рис + овощи", 680, 48.0, 14.0, 82.0),
    ("Перекус: йогурт + орехи", 310, 16.0, 18.0, 22.0),
    ("Ужин: лосось + киноа", 590, 38.0, 22.0, 55.0),
    ("Перекус: тост с авокадо", 280, 9.0, 16.0, 26.0),
]


def _seeded() -> random.Random:
    rng = random.Random()
    rng.seed(42)
    return rng


def populate() -> None:
    """Insert 30 days of mock workouts, recovery, weight, nutrition and products."""
    rng = _seeded()
    today = date.today()

    # Recovery, sleep, HRV — every day
    base_weight = 74.5
    for i in range(30):
        d = today - timedelta(days=29 - i)
        recharge = max(45, min(95, int(rng.gauss(72, 9))))
        hrv = round(max(38, min(72, rng.gauss(56, 6))), 1)
        rhr = max(46, min(62, int(rng.gauss(54, 3))))
        deep = rng.randint(60, 110)
        rem = rng.randint(70, 120)
        light = rng.randint(160, 240)
        wake = rng.randint(8, 25)
        score = max(55, min(95, int(rng.gauss(78, 8))))
        db.upsert_recovery(
            {
                "date": d.isoformat(),
                "nightly_recharge": float(recharge),
                "hrv_ms": hrv,
                "resting_hr": rhr,
                "sleep_duration_min": deep + light + rem + wake,
                "sleep_score": score,
                "deep_sleep_min": deep,
                "light_sleep_min": light,
                "rem_sleep_min": rem,
            }
        )

        # Weight trends slowly downward
        trend = base_weight - i * 0.02 + rng.uniform(-0.4, 0.4)
        db.add_weight(d.isoformat(), round(trend, 1))

        # Nutrition — about 3 meals on weekdays, 2 on weekends
        meals_today = MEALS[: 3 if d.weekday() < 5 else 2]
        for m in meals_today:
            name, kcal, p, f, c = m
            db.add_nutrition_entry(
                {
                    "date": d.isoformat(),
                    "meal_name": name,
                    "kcal": int(kcal + rng.randint(-20, 30)),
                    "protein_g": round(p + rng.uniform(-2, 2), 1),
                    "fat_g": round(f + rng.uniform(-2, 2), 1),
                    "carbs_g": round(c + rng.uniform(-4, 4), 1),
                }
            )

    # Workouts — 4–5 per week, distributed
    workout_days = []
    for week_start_offset in range(0, 30, 7):
        days_in_week = [today - timedelta(days=29 - week_start_offset - j) for j in range(7)]
        chosen = rng.sample(days_in_week, k=min(4 + rng.randint(0, 1), len(days_in_week)))
        workout_days.extend(chosen)
    workout_days = sorted(set(workout_days))
    for idx, d in enumerate(workout_days):
        sport, dist, dur, hr, load = SPORTS[idx % len(SPORTS)]
        dist = round(dist + rng.uniform(-1.5, 1.5), 1)
        dur = int(dur + rng.uniform(-5, 5))
        hr = int(hr + rng.uniform(-5, 5))
        load = round(load + rng.uniform(-10, 10), 1)
        start_dt = datetime.combine(d, time(hour=7, minute=rng.randint(0, 59)))
        db.upsert_workout(
            {
                "polar_id": f"mock-{d.isoformat()}-{idx}",
                "date": d.isoformat(),
                "sport": sport,
                "distance_km": dist,
                "duration_min": dur,
                "avg_hr": hr,
                "max_hr": hr + rng.randint(10, 22),
                "calories": int(dist * 65 + rng.randint(-30, 40)),
                "load_score": load,
                "start_time": start_dt.isoformat(),
                "notes": None,
            }
        )

    for p in PRODUCTS:
        db.add_product(p)
