"""
risk_adapter.py
----------------
Thin translation layer between the ML engines in `multi_disaster_risk_system.py`
and app.py. app.py only ever talks to this file — it never imports the ML
system directly.

Exposes:
    adapter.mode                       -> "ensemble" (trained models loaded) or "fallback"
    adapter.WATCHLIST                  -> list of monitored sites for the live dashboard
    adapter.EQ_REGIONS                 -> list of seismic-zone names (must match the ML file's
                                           _get_indian_state() region names exactly)
    adapter.flood(jun, jul, aug)       -> dict
    adapter.cyclone(lat, lon, month)   -> dict
    adapter.earthquake(month, region)  -> dict
    adapter.combined(payload)          -> dict (flood/cyclone/earthquake sub-reports + overall_*)
    adapter.normalize(hazard_dict, hazard_name) -> {risk_score, risk_category, advice}

If trained model files aren't present under models/ and there's no training
data under data/, the adapter degrades to simple heuristic fallbacks rather
than crashing the app — this keeps the dashboard/demo usable while you get
the real models trained and saved.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

from multi_disaster_risk_system import (
    MultiDisasterRiskSystem,
    risk_category as _risk_category,
)

logger = logging.getLogger("risk_adapter")

ROOT = Path(__file__).resolve().parent
MODEL_DIR = ROOT / "models"
DATA_DIR = ROOT / "data"

load_dotenv(ROOT / ".env")

# Must match the labels EarthquakeRiskEngine._get_indian_state() produces —
# anything else falls into that engine's "Other" bucket and gets filtered out.
EQ_REGIONS = [
    "Northeast India",
    "Himalayan Region",
    "Andaman & Nicobar Islands",
    "Gujarat (Kutch)",
    "Western Ghats",
    "Central India",
    "Southern India",
]

# Sites the background monitor loop in app.py cycles through.
WATCHLIST = [
    {"id": "mangaluru", "name": "Mangaluru, Coastal Karnataka", "hazard": "flood", "lat": 12.9141, "lon": 74.8560},
    {"id": "vizag", "name": "Visakhapatnam", "hazard": "cyclone", "lat": 17.6868, "lon": 83.2185},
    {"id": "chennai", "name": "Chennai", "hazard": "cyclone", "lat": 13.0827, "lon": 80.2707},
    {"id": "srinagar", "name": "Srinagar", "hazard": "earthquake", "lat": 34.0837, "lon": 74.7973},
    {"id": "bhuj", "name": "Bhuj, Gujarat (Kutch)", "hazard": "earthquake", "lat": 23.2420, "lon": 69.6669},
    {"id": "portblair", "name": "Port Blair", "hazard": "earthquake", "lat": 11.6234, "lon": 92.7265},
]


class RiskAdapter:
    def __init__(self) -> None:
        self.system = MultiDisasterRiskSystem()
        self.WATCHLIST = WATCHLIST
        self.EQ_REGIONS = EQ_REGIONS
        self.mode = "fallback"
        self._load_or_train()

    # ------------------------------------------------------------------ #
    # startup: try pretrained models first, fall back to training, then
    # fall back to heuristics if neither is available
    # ------------------------------------------------------------------ #
    def _load_or_train(self) -> None:
        flood_path = DATA_DIR / "rainfall.xlsx"
        cyclone_path = DATA_DIR / "Cyclone_Dataset.xlsx"
        earthquake_path = DATA_DIR / "Earthquakes.csv"

        try:
            for engine in self.system.engines.values():
                engine.load()

            # Loading joblib restores the ML pipelines. These two engines also
            # require data-derived state at prediction time, so restore it here
            # without retraining the saved pipelines.
            self.system.engines["cyclone"].load_and_engineer(cyclone_path)
            self.system.engines["earthquake"].load_and_engineer(earthquake_path)

            self.mode = "ensemble"
            logger.info(
                "Loaded pretrained models from %s and restored cyclone/earthquake data state.",
                MODEL_DIR,
            )
            return
        except Exception as exc:
            logger.warning("Could not load pretrained models (%s).", exc)

        if flood_path.exists() and cyclone_path.exists() and earthquake_path.exists():
            try:
                logger.info("Training models from %s (this can take a while)...", DATA_DIR)
                self.system.train_all(flood_path, cyclone_path, earthquake_path)
                self.mode = "ensemble"
                return
            except Exception as exc:
                logger.error("Training failed (%s). Running in fallback mode.", exc)
        else:
            logger.warning(
                "No pretrained models in %s and no training data in %s — running in fallback mode.",
                MODEL_DIR, DATA_DIR,
            )

        self.mode = "fallback"

    # ------------------------------------------------------------------ #
    # normalize: collapse any hazard's report into a common shape
    # ------------------------------------------------------------------ #
    def normalize(self, hazard_report: dict, hazard_name: str) -> dict:
        if not hazard_report:
            return {"risk_score": 0.0, "risk_category": "LOW", "advice": ""}
        score = float(hazard_report.get("risk_score", 0.0) or 0.0)
        category = str(
            hazard_report.get("risk_category")
            or hazard_report.get("risk_level")
            or "LOW"
        ).upper()
        advice = hazard_report.get("advice") or hazard_report.get("recommendation") or ""
        return {"risk_score": score, "risk_category": category, "advice": advice}

    # ------------------------------------------------------------------ #
    # per-hazard calls used by /api/assess and the monitor loop
    # ------------------------------------------------------------------ #
    def flood(self, jun: float, jul: float, aug: float) -> dict:
        if self.mode == "ensemble":
            try:
                return self.system.flood_risk({"JUN": jun, "JUL": jul, "AUG": aug})
            except Exception as exc:
                logger.warning("flood_risk failed (%s); using fallback heuristic", exc)
        return self._fallback_flood(jun, jul, aug)

    def cyclone(self, lat: float, lon: float, month: Optional[int] = None) -> dict:
        if self.mode == "ensemble":
            try:
                return self.system.cyclone_risk(lat, lon, month)
            except Exception as exc:
                logger.warning("cyclone_risk failed (%s); using fallback heuristic", exc)
        return self._fallback_cyclone(lat, lon, month)

    def earthquake(self, month: Any, region: str) -> dict:
        if self.mode == "ensemble":
            try:
                return self.system.earthquake_risk(month, region)
            except Exception as exc:
                logger.warning("earthquake_risk failed (%s); using fallback heuristic", exc)
        return self._fallback_earthquake(month, region)

    def nowcast(self, lat: float, lon: float, month_name: Optional[str] = None) -> dict:
        """Short-term (10-day) rainfall nowcast via the Google Weather API.

        This is informational only — it is never used to trigger fund
        disbursal, only to surface an early warning on the dashboard.
        """
        api_key = os.getenv("GOOGLE_MAPS_API_KEY")
        if not api_key:
            return {
                "error": "GOOGLE_MAPS_API_KEY is not configured on the server. "
                         "Add it to your .env file to enable the live nowcast.",
            }

        if self.system.nowcast is None:
            try:
                self.system.setup_nowcast(api_key)
            except Exception as exc:
                logger.error("Failed to initialize Google Weather nowcast: %s", exc)
                return {"error": f"Could not initialize the nowcast client: {exc}"}

        if month_name is None:
            import datetime
            month_name = datetime.date.today().strftime("%b").upper()

        try:
            return self.system.flood_nowcast(lat, lon, month_name)
        except Exception as exc:
            logger.error("Nowcast fetch failed: %s", exc)
            return {"error": f"Could not fetch the forecast right now: {exc}"}

    def combined(self, payload: dict) -> dict:
        rainfall = payload.get("rainfall") or {}
        report: dict = {}

        if rainfall:
            report["flood"] = self.flood(
                rainfall.get("JUN", 0), rainfall.get("JUL", 0), rainfall.get("AUG", 0)
            )
        if payload.get("lat") is not None and payload.get("lon") is not None:
            report["cyclone"] = self.cyclone(payload["lat"], payload["lon"], payload.get("month"))

        eq_region = payload.get("eq_region")
        eq_month = payload.get("eq_month") or payload.get("month")
        if eq_region and eq_month:
            report["earthquake"] = self.earthquake(eq_month, eq_region)

        report["engine_mode"] = self.mode
        scores = [r.get("risk_score", 0) for r in report.values() if isinstance(r, dict)]
        if scores:
            overall = max(scores)
            report["overall_regional_risk_index"] = round(overall, 1)
            report["overall_regional_risk_category"] = _risk_category(overall / 100)["risk_category"]
        else:
            report["overall_regional_risk_index"] = 0.0
            report["overall_regional_risk_category"] = "LOW"
        return report

    # ------------------------------------------------------------------ #
    # heuristic fallbacks — only used when no trained model is available,
    # so the dashboard still functions rather than 500ing on every request
    # ------------------------------------------------------------------ #
    def _fallback_flood(self, jun: float, jul: float, aug: float) -> dict:
        total = (jun or 0) + (jul or 0) + (aug or 0)
        score = max(0.0, min(100.0, (total - 300) / 8))
        result = _risk_category(score / 100)
        result.update({"hazard": "flood", "will_occur": score >= 50, "probability": round(score / 100, 4)})
        return result

    def _fallback_cyclone(self, lat: float, lon: float, month: Optional[int]) -> dict:
        result = _risk_category(0.08)
        result.update({"hazard": "cyclone", "month": month, "month_name": ""})
        return result

    def _fallback_earthquake(self, month: Any, region: str) -> dict:
        return {
            "region": region,
            "month": str(month),
            "risk_level": "LOW",
            "risk_score": 10.0,
            "statistics": {},
            "recommendation": "Model unavailable — showing a placeholder low-risk reading.",
        }
