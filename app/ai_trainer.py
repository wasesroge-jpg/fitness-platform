"""Claude API integration for the AI trainer page."""
from __future__ import annotations

import json
import os
from datetime import date, timedelta
from typing import Any

from . import database as db


SYSTEM_PROMPT = (
    "You are a personal sports coach AI. You have access to the user's real "
    "training data. Always reference specific numbers from their data in your "
    "responses. Be concise, practical, and data-driven. Respond in the same "
    "language the user writes in."
)


def build_context(days: int = 14) -> dict[str, Any]:
    """Build a JSON-serialisable context dict summarising the last N days."""
    today = date.today()
    since = (today - timedelta(days=days - 1)).isoformat()

    recovery = db.recovery_range(days)
    workouts = db.list_workouts(since=since)
    weight = db.weight_range(days)
    goals = db.get_goals()

    nutrition: list[dict] = []
    for i in range(days):
        d = (today - timedelta(days=days - 1 - i)).isoformat()
        totals = db.nutrition_totals(d)
        totals["date"] = d
        nutrition.append(totals)

    return {
        "as_of": today.isoformat(),
        "recovery": recovery,
        "workouts": workouts,
        "weight": weight,
        "goals": goals,
        "nutrition": nutrition,
    }


def offline_reply(message: str, context: dict[str, Any]) -> str:
    """Deterministic, data-driven fallback response when no API key is set.

    Used so the page works without ANTHROPIC_API_KEY.
    """
    recovery = [r for r in context["recovery"] if r.get("nightly_recharge")]
    last_rec = recovery[-1] if recovery else None
    load_7d = sum(
        w.get("load_score") or 0
        for w in context["workouts"]
        if w["date"] >= (date.today() - timedelta(days=6)).isoformat()
    )
    parts: list[str] = []
    if last_rec:
        parts.append(
            f"Восстановление вчера: {last_rec['nightly_recharge']:.0f}%, "
            f"HRV {last_rec['hrv_ms']:.0f} мс, пульс покоя {last_rec['resting_hr']} уд/мин."
        )
    parts.append(f"Нагрузка за 7 дней: {load_7d:.0f}.")
    msg_lower = message.lower()
    if "уст" in msg_lower or "tired" in msg_lower:
        parts.append(
            "С такими данными лучше лёгкая Z2-пробежка 30–40 минут или полный отдых."
        )
    elif "марафон" in msg_lower or "marathon" in msg_lower:
        parts.append(
            "Базовый план на марафон: 4 пробежки в неделю — 2 Z2, 1 темп, 1 длительная."
        )
    elif "плав" in msg_lower or "swim" in msg_lower:
        parts.append(
            "Добавь техничный заплыв 4×100 м + 8×50 м после дня восстановления."
        )
    elif "зон" in msg_lower or "zone" in msg_lower:
        parts.append(
            "Зоны по ЧСС: Z1 50–60%, Z2 60–70%, Z3 70–80%, Z4 80–90%, Z5 90–100% от максимума."
        )
    else:
        parts.append(
            "Спроси меня про план на неделю, восстановление, питание или конкретную тренировку."
        )
    parts.append("(Локальный режим: ANTHROPIC_API_KEY не задан.)")
    return " ".join(parts)


def chat(message: str, context: dict[str, Any] | None = None) -> str:
    if context is None:
        context = build_context()
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return offline_reply(message, context)
    try:
        import anthropic
    except ImportError:
        return offline_reply(message, context)
    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Context: {json.dumps(context, ensure_ascii=False)}\n\n"
                        f"User: {message}"
                    ),
                }
            ],
        )
        return "".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        ).strip()
    except Exception as exc:  # noqa: BLE001 — surface any API failure as text
        return f"AI-тренер временно недоступен: {exc}"
