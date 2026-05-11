"""Polar AccessLink API client.

This is a thin wrapper around the Polar AccessLink REST API. If credentials are
missing or the API returns an error, the methods raise PolarError so callers can
fall back to mock data.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from typing import Any

import requests

from . import database as db


POLAR_BASE = "https://www.polaraccesslink.com/v3"


class PolarError(RuntimeError):
    pass


class PolarClient:
    def __init__(self, access_token: str | None = None, user_id: str | None = None):
        self.access_token = access_token or os.environ.get("POLAR_ACCESS_TOKEN")
        self.user_id = user_id or os.environ.get("POLAR_USER_ID")

    @property
    def configured(self) -> bool:
        return bool(self.access_token and self.user_id)

    def _headers(self) -> dict:
        if not self.access_token:
            raise PolarError("POLAR_ACCESS_TOKEN is not set")
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
        }

    def _get(self, path: str, **params: Any) -> Any:
        try:
            r = requests.get(
                f"{POLAR_BASE}{path}", headers=self._headers(), params=params, timeout=15
            )
        except requests.RequestException as exc:
            raise PolarError(f"Network error talking to Polar: {exc}") from exc
        if r.status_code == 204:
            return None
        if not r.ok:
            raise PolarError(f"Polar API error {r.status_code}: {r.text[:200]}")
        try:
            return r.json()
        except ValueError as exc:
            raise PolarError(f"Polar returned non-JSON: {exc}") from exc

    # -------- public API methods --------

    def get_nightly_recharge(self, target: date) -> dict | None:
        """Return nightly recharge for a given date or None if unavailable."""
        if not self.configured:
            raise PolarError("Polar credentials not configured")
        data = self._get(
            f"/users/{self.user_id}/nightly-recharge",
            from_=target.isoformat(),
            to=target.isoformat(),
        )
        if not data:
            return None
        # Polar returns a list under `nightly_recharges`
        items = data.get("nightly_recharges") or data.get("nightlyRecharges") or []
        if not items:
            return None
        item = items[0]
        return {
            "date": target.isoformat(),
            "nightly_recharge": float(item.get("nightlyRechargeStatus") or 0),
            "hrv_ms": float(item.get("hrvAvg") or 0),
            "resting_hr": int(item.get("restingHeartRate") or 0),
        }

    def get_sleep(self, target: date) -> dict | None:
        if not self.configured:
            raise PolarError("Polar credentials not configured")
        data = self._get(
            f"/users/{self.user_id}/sleep", date=target.isoformat()
        )
        if not data or "nights" not in data or not data["nights"]:
            return None
        night = data["nights"][0]
        return {
            "date": target.isoformat(),
            "sleep_duration_min": int(night.get("sleepEndTime", 0)),
            "sleep_score": int(night.get("sleepScore") or 0),
            "deep_sleep_min": int(night.get("deepSleep") or 0),
            "light_sleep_min": int(night.get("lightSleep") or 0),
            "rem_sleep_min": int(night.get("remSleep") or 0),
        }

    def get_exercises(self, since: date) -> list[dict]:
        if not self.configured:
            raise PolarError("Polar credentials not configured")
        data = self._get(f"/users/{self.user_id}/exercise-transactions")
        items = (data or {}).get("exercises") or []
        out = []
        for e in items:
            start = e.get("start-time") or e.get("startTime") or ""
            try:
                start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                d = start_dt.date()
            except ValueError:
                continue
            if d < since:
                continue
            out.append(
                {
                    "polar_id": str(e.get("id") or e.get("polarUser") or start),
                    "date": d.isoformat(),
                    "sport": (e.get("sport") or "OTHER").lower(),
                    "distance_km": round(
                        float(e.get("distance") or 0) / 1000.0, 2
                    ),
                    "duration_min": int(float(e.get("duration_seconds") or 0) / 60),
                    "avg_hr": int(e.get("heart-rate", {}).get("average") or 0),
                    "max_hr": int(e.get("heart-rate", {}).get("maximum") or 0),
                    "calories": int(e.get("calories") or 0),
                    "load_score": round(float(e.get("training-load") or 0), 1),
                    "start_time": start,
                    "notes": None,
                }
            )
        return out

    def get_daily_activity(self, target: date) -> dict | None:
        if not self.configured:
            raise PolarError("Polar credentials not configured")
        data = self._get(
            f"/users/{self.user_id}/activity-transactions"
        )
        items = (data or {}).get("activity-log") or []
        for a in items:
            if a.get("date") == target.isoformat():
                return {
                    "date": a["date"],
                    "steps": int(a.get("active-steps") or 0),
                    "calories": int(a.get("calories") or 0),
                }
        return None

    def sync_last_30_days(self) -> dict:
        """Pull last 30 days from Polar and upsert into SQLite."""
        if not self.configured:
            raise PolarError("Polar credentials not configured")
        today = date.today()
        since = today - timedelta(days=29)
        counts = {"workouts": 0, "recovery": 0}
        for offset in range(30):
            d = since + timedelta(days=offset)
            try:
                nr = self.get_nightly_recharge(d)
                sleep = self.get_sleep(d)
            except PolarError:
                nr, sleep = None, None
            rec = {
                "date": d.isoformat(),
                "nightly_recharge": (nr or {}).get("nightly_recharge"),
                "hrv_ms": (nr or {}).get("hrv_ms"),
                "resting_hr": (nr or {}).get("resting_hr"),
                "sleep_duration_min": (sleep or {}).get("sleep_duration_min"),
                "sleep_score": (sleep or {}).get("sleep_score"),
                "deep_sleep_min": (sleep or {}).get("deep_sleep_min"),
                "light_sleep_min": (sleep or {}).get("light_sleep_min"),
                "rem_sleep_min": (sleep or {}).get("rem_sleep_min"),
            }
            if nr or sleep:
                db.upsert_recovery(rec)
                counts["recovery"] += 1
        try:
            exercises = self.get_exercises(since)
        except PolarError:
            exercises = []
        for ex in exercises:
            db.upsert_workout(ex)
            counts["workouts"] += 1
        return counts
