"""Flask entry point — all routes for the fitness platform."""
from __future__ import annotations

import io
import os
from datetime import date, datetime, timedelta
from typing import Any

from dotenv import load_dotenv
from flask import (
    Flask,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

# Allow running as `python app.py` from inside app/ as well as `python -m app.app`.
try:
    from . import ai_trainer, database as db, fit_export, mock_data
    from .polar import PolarClient, PolarError
except ImportError:  # pragma: no cover - script-mode fallback
    import sys

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from app import ai_trainer, database as db, fit_export, mock_data  # type: ignore
    from app.polar import PolarClient, PolarError  # type: ignore


load_dotenv()


SPORT_COLORS = {
    "running": "#3ecf8e",
    "cycling": "#5b8af5",
    "swimming": "#5bd5f5",
    "swim": "#5bd5f5",
    "strength": "#c77df5",
    "training": "#c77df5",
    "walking": "#f5a623",
    "rowing": "#f5a623",
    "other": "#8892a8",
}


def create_app() -> Flask:
    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")

    db.init_db()
    if db.is_empty():
        mock_data.populate()

    @app.template_filter("nice_date")
    def nice_date(value: str) -> str:
        try:
            return datetime.fromisoformat(value).strftime("%d.%m")
        except Exception:
            return value

    @app.context_processor
    def inject_globals() -> dict[str, Any]:
        return {"sport_colors": SPORT_COLORS, "today": date.today().isoformat()}

    # ---------------------- Dashboard ----------------------

    @app.route("/")
    def dashboard():
        latest = db.latest_recovery() or {}
        recovery_pct = int(latest.get("nightly_recharge") or 0)
        hrv = int(latest.get("hrv_ms") or 0)
        resting_hr = int(latest.get("resting_hr") or 0)
        load_7d = db.training_load(7)
        load_14 = db.daily_load(14)
        recovery_14 = db.recovery_range(14)
        sleep = {
            "duration_min": int(latest.get("sleep_duration_min") or 0),
            "score": int(latest.get("sleep_score") or 0),
            "deep": int(latest.get("deep_sleep_min") or 0),
            "light": int(latest.get("light_sleep_min") or 0),
            "rem": int(latest.get("rem_sleep_min") or 0),
            "wake": max(
                0,
                int(latest.get("sleep_duration_min") or 0)
                - int(latest.get("deep_sleep_min") or 0)
                - int(latest.get("light_sleep_min") or 0)
                - int(latest.get("rem_sleep_min") or 0),
            ),
        }
        workouts = db.recent_workouts(5)
        status, advice = _recovery_advice(recovery_pct)
        fatigue = min(100, int(load_7d / 4))
        month = _mini_calendar(date.today())
        return render_template(
            "dashboard.html",
            page="dashboard",
            recovery_pct=recovery_pct,
            hrv=hrv,
            resting_hr=resting_hr,
            load_7d=load_7d,
            load_14=load_14,
            recovery_14=recovery_14,
            sleep=sleep,
            workouts=workouts,
            status=status,
            advice=advice,
            fatigue=fatigue,
            month=month,
        )

    # ---------------------- Calendar ----------------------

    @app.route("/calendar")
    def calendar():
        try:
            y = int(request.args.get("y") or date.today().year)
            m = int(request.args.get("m") or date.today().month)
        except ValueError:
            abort(400)
        month = _calendar_grid(y, m)
        prev_y, prev_m = (y - 1, 12) if m == 1 else (y, m - 1)
        next_y, next_m = (y + 1, 1) if m == 12 else (y, m + 1)
        return render_template(
            "calendar.html",
            page="calendar",
            month=month,
            year=y,
            month_num=m,
            month_name=_month_name(m),
            prev_y=prev_y,
            prev_m=prev_m,
            next_y=next_y,
            next_m=next_m,
        )

    @app.route("/day/<d>")
    def day_detail(d: str):
        try:
            datetime.fromisoformat(d)
        except ValueError:
            abort(400)
        workouts = db.workouts_by_date(d)
        note = db.get_note(d)
        return jsonify(
            {
                "date": d,
                "pretty_date": datetime.fromisoformat(d).strftime("%d.%m.%Y"),
                "workouts": workouts,
                "note": note,
            }
        )

    @app.route("/day/<d>/note", methods=["POST"])
    def save_note(d: str):
        try:
            datetime.fromisoformat(d)
        except ValueError:
            abort(400)
        note = (request.json or request.form).get("note", "")
        db.set_note(d, note)
        return jsonify({"ok": True})

    # ---------------------- Nutrition ----------------------

    @app.route("/nutrition")
    def nutrition():
        today = date.today().isoformat()
        totals = db.nutrition_totals(today)
        goals = db.get_goals()
        meals = db.nutrition_for_date(today)
        weight = db.weight_range(14)
        products = db.list_products()
        return render_template(
            "nutrition.html",
            page="nutrition",
            today=today,
            totals=totals,
            goals=goals,
            meals=meals,
            weight=weight,
            products=products,
        )

    @app.route("/nutrition/add", methods=["POST"])
    def nutrition_add():
        form = request.form
        entry = {
            "date": form.get("date") or date.today().isoformat(),
            "meal_name": (form.get("meal_name") or "Без названия").strip(),
            "kcal": int(form.get("kcal") or 0),
            "protein_g": float(form.get("protein_g") or 0),
            "fat_g": float(form.get("fat_g") or 0),
            "carbs_g": float(form.get("carbs_g") or 0),
        }
        grams = float(form.get("grams") or 0)
        if grams and entry["kcal"] == 0 and form.get("product_id"):
            # If a product is selected and grams given, scale macros from per-100g values.
            pid = int(form["product_id"])
            for p in db.list_products():
                if p["id"] == pid:
                    factor = grams / 100.0
                    entry["meal_name"] = f"{p['name']} ({int(grams)} г)"
                    entry["kcal"] = int(p["kcal_per_100g"] * factor)
                    entry["protein_g"] = round(p["protein_g"] * factor, 1)
                    entry["fat_g"] = round(p["fat_g"] * factor, 1)
                    entry["carbs_g"] = round(p["carbs_g"] * factor, 1)
                    break
        db.add_nutrition_entry(entry)
        return redirect(url_for("nutrition"))

    @app.route("/nutrition/product/add", methods=["POST"])
    def product_add():
        form = request.form
        db.add_product(
            {
                "name": (form.get("name") or "Без названия").strip(),
                "kcal_per_100g": int(form.get("kcal_per_100g") or 0),
                "protein_g": float(form.get("protein_g") or 0),
                "fat_g": float(form.get("fat_g") or 0),
                "carbs_g": float(form.get("carbs_g") or 0),
            }
        )
        return redirect(url_for("nutrition"))

    @app.route("/weight/add", methods=["POST"])
    def weight_add():
        form = request.form
        kg = float(form.get("weight_kg") or 0)
        d = form.get("date") or date.today().isoformat()
        if kg <= 0:
            abort(400)
        db.add_weight(d, kg)
        return redirect(url_for("nutrition"))

    # ---------------------- AI trainer ----------------------

    @app.route("/ai")
    def ai_page():
        ctx = ai_trainer.build_context(14)
        plan = _week_plan(ctx)
        last3 = db.recent_workouts(3)
        latest = db.latest_recovery() or {}
        sidebar_ctx = {
            "recovery_pct": int(latest.get("nightly_recharge") or 0),
            "hrv": int(latest.get("hrv_ms") or 0),
            "load_7d": db.training_load(7),
            "sleep_min": int(latest.get("sleep_duration_min") or 0),
            "resting_hr": int(latest.get("resting_hr") or 0),
        }
        return render_template(
            "ai_trainer.html",
            page="ai",
            sidebar_ctx=sidebar_ctx,
            last3=last3,
            plan=plan,
        )

    @app.route("/ai/chat", methods=["POST"])
    def ai_chat():
        body = request.json or {}
        message = (body.get("message") or "").strip()
        if not message:
            return jsonify({"reply": "Напиши свой вопрос — я отвечу на основе твоих данных."})
        ctx = ai_trainer.build_context(14)
        reply = ai_trainer.chat(message, ctx)
        return jsonify({"reply": reply})

    @app.route("/ai/export-fit")
    def ai_export_fit():
        ctx = ai_trainer.build_context(14)
        plan = _week_plan(ctx)
        scheduled = []
        for entry in plan:
            if entry.get("rest"):
                continue
            scheduled.append(
                {
                    "name": entry["name"],
                    "sport": entry["sport"],
                    "distance_km": entry["distance_km"],
                    "duration_min": entry["duration_min"],
                    "scheduled_at": datetime.fromisoformat(entry["date"] + "T07:00:00"),
                }
            )
        if not scheduled:  # pragma: no cover - safety fallback
            scheduled = [
                {
                    "name": "Easy run",
                    "sport": "running",
                    "distance_km": 6.0,
                    "duration_min": 35,
                    "scheduled_at": datetime.utcnow(),
                }
            ]
        blob = fit_export.build_fit(scheduled)
        return send_file(
            io.BytesIO(blob),
            mimetype="application/vnd.ant.fit",
            as_attachment=True,
            download_name=f"week_plan_{date.today().isoformat()}.fit",
        )

    # ---------------------- Sync ----------------------

    @app.route("/sync")
    def sync():
        client = PolarClient()
        if not client.configured:
            return jsonify(
                {
                    "ok": False,
                    "error": "Polar credentials not configured. Using mock data.",
                }
            ), 400
        try:
            counts = client.sync_last_30_days()
            return jsonify({"ok": True, "synced": counts})
        except PolarError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 502

    return app


# ---------------------- Helpers ----------------------

def _recovery_advice(pct: int) -> tuple[str, str]:
    if pct >= 80:
        return ("Excellent", "Можно ключевая тренировка: интервалы или темповой бег.")
    if pct >= 65:
        return ("Good", "Готов к качественной работе. Кардио Z3-Z4 или силовая.")
    if pct >= 50:
        return ("Moderate", "Аэробный объём в Z2, без жёстких интервалов.")
    return ("Poor", "Восстановление низкое. Лучше отдых или 30 мин ходьбы.")


def _mini_calendar(today: date) -> dict:
    """Return mini-calendar dict for the current month."""
    return _calendar_grid(today.year, today.month)


def _calendar_grid(year: int, month: int) -> dict:
    """Build a 6-row, 7-col grid for given month, with workout dots."""
    first = date(year, month, 1)
    # Monday-first week
    start_weekday = first.weekday()
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    last_day = (next_month - timedelta(days=1)).day

    # Pull workouts in [first, last] (with a small buffer)
    workouts = db.list_workouts(
        since=first.isoformat(), until=next_month.isoformat()
    )
    by_date: dict[str, list[dict]] = {}
    for w in workouts:
        by_date.setdefault(w["date"], []).append(w)

    weeks: list[list[dict]] = []
    week: list[dict] = []
    for _ in range(start_weekday):
        week.append({"empty": True})
    for day_num in range(1, last_day + 1):
        d = date(year, month, day_num)
        ws = by_date.get(d.isoformat(), [])
        week.append(
            {
                "empty": False,
                "day": day_num,
                "date": d.isoformat(),
                "is_today": d == date.today(),
                "workouts": ws,
                "sport_colors": [
                    SPORT_COLORS.get(w["sport"], "#8892a8") for w in ws
                ],
            }
        )
        if len(week) == 7:
            weeks.append(week)
            week = []
    if week:
        while len(week) < 7:
            week.append({"empty": True})
        weeks.append(week)
    return {"weeks": weeks}


def _month_name(month: int) -> str:
    names = [
        "Январь",
        "Февраль",
        "Март",
        "Апрель",
        "Май",
        "Июнь",
        "Июль",
        "Август",
        "Сентябрь",
        "Октябрь",
        "Ноябрь",
        "Декабрь",
    ]
    return names[month - 1] if 1 <= month <= 12 else str(month)


def _week_plan(context: dict[str, Any]) -> list[dict]:
    """Build a simple 7-day plan based on recent recovery and load."""
    today = date.today()
    # Monday of this week
    monday = today - timedelta(days=today.weekday())
    avg_recharge = 70
    rec = [r for r in context.get("recovery", []) if r.get("nightly_recharge")]
    if rec:
        avg_recharge = sum(r["nightly_recharge"] for r in rec) / len(rec)

    template = [
        ("Z2 easy run", "running", 8.0, 50),
        ("Strength + core", "training", 0.0, 45),
        ("Tempo run", "running", 10.0, 55),
        ("Rest", "rest", 0.0, 0),
        ("Swim technique", "swimming", 1.5, 40),
        ("Long run", "running", 14.0, 90),
        ("Recovery walk", "walking", 4.0, 45),
    ]
    plan = []
    for i, (name, sport, dist, dur) in enumerate(template):
        d = monday + timedelta(days=i)
        is_rest = sport == "rest"
        # Auto-rest on low recovery
        if avg_recharge < 60 and sport == "running" and i in (2,):
            name, sport, dist, dur, is_rest = "Easy Z2 only", "running", 5.0, 30, False
        plan.append(
            {
                "date": d.isoformat(),
                "weekday": _weekday_name(d.weekday()),
                "name": name,
                "sport": sport,
                "distance_km": dist,
                "duration_min": dur,
                "color": SPORT_COLORS.get(sport, "#8892a8")
                if not is_rest
                else "#3c4256",
                "rest": is_rest,
            }
        )
    return plan


def _weekday_name(idx: int) -> str:
    return ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][idx]


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
