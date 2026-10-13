"""
================================================================================
 MULTI-DISASTER RISK PREDICTION SYSTEM
 Flood (rainfall-based) + Cyclone (climatological risk-based) + Earthquake
 engines built on Stacking Ensembles, with a pluggable architecture.

 UPDATED CYCLONE ENGINE: Now uses climatological risk assessment requiring
 only latitude and longitude as inputs. Month is automatically detected
 from the current date.

 Run this file directly for an interactive CLI demo:
    python multi_disaster_risk_system.py
================================================================================
"""

import os
import re
import datetime
import warnings
import json
from abc import ABC, abstractmethod
from pathlib import Path

import numpy as np
import pandas as pd
import joblib

from sklearn.model_selection import train_test_split
from sklearn.ensemble import (
    RandomForestClassifier,
    GradientBoostingClassifier,
    ExtraTreesClassifier,
    StackingClassifier,
)
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import classification_report, roc_auc_score, confusion_matrix
from imblearn.over_sampling import SMOTE
from imblearn.pipeline import Pipeline as ImbPipeline
import xgboost as xgb

warnings.filterwarnings("ignore")

RANDOM_STATE = 42
MODEL_DIR = Path("models")
MODEL_DIR.mkdir(exist_ok=True)


# ==============================================================================
# SHARED UTILITIES
# ==============================================================================

def risk_category(prob: float) -> dict:
    """Convert a model probability (0-1) into a risk index (0-100),
    a category label, and short guidance text."""
    score = round(prob * 100, 1)
    if score < 25:
        label, advice = "LOW", "No unusual precautions needed. Continue routine monitoring."
    elif score < 50:
        label, advice = "MODERATE", "Stay alert to official bulletins; review local emergency plans."
    elif score < 75:
        label, advice = "HIGH", "Prepare emergency kits, monitor forecasts closely, avoid flood/coastal-prone travel."
    else:
        label, advice = "SEVERE", "Immediate precaution advised. Follow evacuation/advisory guidance from local authorities."
    return {"risk_score": score, "risk_category": label, "advice": advice}


def sid_to_month(sid: str) -> int:
    """IBTrACS-style SID e.g. '2010136N09057' encodes YYYY + day-of-year.
    Decode it into a calendar month (used as a genesis-time feature)."""
    m = re.match(r"(\d{4})(\d{3})", str(sid))
    if not m:
        return 6  # Default to June if parsing fails
    year, doy = int(m.group(1)), int(m.group(2))
    d = datetime.date(year, 1, 1) + datetime.timedelta(days=doy - 1)
    return d.month


# ==============================================================================
# ABSTRACT BASE — lets us plug in Earthquake (or any hazard) later with the
# exact same interface: load_data -> build_features -> train -> predict_risk
# ==============================================================================

class DisasterRiskEngine(ABC):
    hazard_name = "generic"

    def __init__(self):
        self.pipeline = None
        self.feature_columns = []
        self.metrics_ = {}

    def _build_stack(self, extra_trees=False):
        base_learners = [
            ("rf", RandomForestClassifier(
                n_estimators=300, max_depth=6, random_state=RANDOM_STATE,
                class_weight="balanced")),
            ("gb", GradientBoostingClassifier(
                n_estimators=200, max_depth=3, random_state=RANDOM_STATE)),
            ("xgb", xgb.XGBClassifier(
                n_estimators=200, max_depth=4, eval_metric="logloss",
                random_state=RANDOM_STATE)),
        ]
        if extra_trees:
            base_learners.append(
                ("et", ExtraTreesClassifier(
                    n_estimators=300, max_depth=6, random_state=RANDOM_STATE,
                    class_weight="balanced"))
            )
        meta_learner = LogisticRegression(max_iter=1000)
        return StackingClassifier(
            estimators=base_learners, final_estimator=meta_learner,
            cv=5, passthrough=False, n_jobs=-1
        )

    @abstractmethod
    def load_and_engineer(self, path):
        """Return X (DataFrame), y (Series)."""
        raise NotImplementedError

    def train(self, path, extra_trees=False, test_size=0.2):
        X, y = self.load_and_engineer(path)
        self.feature_columns = list(X.columns)

        Xtr, Xte, ytr, yte = train_test_split(
            X, y, test_size=test_size, stratify=y, random_state=RANDOM_STATE
        )

        stack = self._build_stack(extra_trees=extra_trees)
        self.pipeline = ImbPipeline([
            ("scaler", StandardScaler()),
            ("smote", SMOTE(random_state=RANDOM_STATE, k_neighbors=3)),
            ("stack", stack),
        ])
        self.pipeline.fit(Xtr, ytr)

        pred = self.pipeline.predict(Xte)
        proba = self.pipeline.predict_proba(Xte)[:, 1]
        self.metrics_ = {
            "report": classification_report(yte, pred, output_dict=True),
            "roc_auc": roc_auc_score(yte, proba) if len(set(yte)) > 1 else None,
            "confusion_matrix": confusion_matrix(yte, pred).tolist(),
            "n_train": len(Xtr),
            "n_test": len(Xte),
        }
        print(f"\n[{self.hazard_name.upper()}] Stacking ensemble trained on "
              f"{len(Xtr)} samples, tested on {len(Xte)}.")
        print(classification_report(yte, pred))
        if self.metrics_["roc_auc"] is not None:
            print(f"ROC-AUC: {self.metrics_['roc_auc']:.3f}")
        return self.metrics_

    def predict_risk(self, feature_row: dict) -> dict:
        if self.pipeline is None:
            raise RuntimeError(f"{self.hazard_name} model is not trained yet.")
        row = pd.DataFrame([feature_row])[self.feature_columns]
        prob = self.pipeline.predict_proba(row)[0, 1]
        result = risk_category(prob)
        result["hazard"] = self.hazard_name
        result["will_occur"] = bool(prob >= 0.5)
        result["probability"] = round(float(prob), 4)
        return result

    def save(self):
        path = MODEL_DIR / f"{self.hazard_name}_model.joblib"
        joblib.dump({"pipeline": self.pipeline, "features": self.feature_columns}, path)
        print(f"Saved {self.hazard_name} model -> {path}")

    def load(self):
        path = MODEL_DIR / f"{self.hazard_name}_model.joblib"
        payload = joblib.load(path)
        self.pipeline = payload["pipeline"]
        self.feature_columns = payload["features"]


# ==============================================================================
# FLOOD ENGINE — driven by rainfall.xlsx
# ==============================================================================

class FloodRiskEngine(DisasterRiskEngine):
    """
    DESIGN CHOICE: this engine uses JUNE-AUGUST rainfall --
    the core monsoon window IMD's own "Subdivision-wise Rainfall
    Distribution" report tracks and publishes as a running cumulative
    total.

    This is a MONSOON-SEASON RISK ASSESSMENT tool, not a pre-season forecast.
    """
    hazard_name = "flood"
    MONTHS = ["JUN", "JUL", "AUG"]  # core monsoon window IMD reports on

    def __init__(self):
        super().__init__()
        self._hist_mean = None
        self._hist_std = None

    def load_and_engineer(self, path):
        df = pd.read_excel(path)

        df["JJA_TOTAL"] = df[self.MONTHS].sum(axis=1)
        df["JJA_VARIABILITY"] = df[self.MONTHS].std(axis=1)
        df["TREND"] = df["AUG"] - df["JUN"]  # is the monsoon intensifying or tapering?

        # historical anomaly computed against Jun-Aug totals only
        self._hist_mean = df["JJA_TOTAL"].mean()
        self._hist_std = df["JJA_TOTAL"].std()
        df["JJA_ANOMALY"] = (df["JJA_TOTAL"] - self._hist_mean) / self._hist_std

        feature_cols = self.MONTHS + ["JJA_TOTAL", "JJA_VARIABILITY", "TREND", "JJA_ANOMALY"]
        X = df[feature_cols].fillna(0)
        y = (df["Flood"].astype(str).str.strip().str.lower() == "yes").astype(int)
        return X, y

    def train(self, path, **kwargs):
        return super().train(path, extra_trees=True, **kwargs)

    def build_input(self, monthly_rainfall: dict) -> dict:
        """Turn 3 raw monsoon-month rainfall figures (mm, Jun-Aug) into the
        engineered feature row the model expects."""
        vals = {m: float(monthly_rainfall.get(m, 0.0)) for m in self.MONTHS}
        jja_total = sum(vals.values())
        variability = float(np.std(list(vals.values())))
        trend = vals["AUG"] - vals["JUN"]
        anomaly = (jja_total - self._hist_mean) / self._hist_std if self._hist_std else 0

        row = dict(vals)
        row.update({
            "JJA_TOTAL": jja_total,
            "JJA_VARIABILITY": variability,
            "TREND": trend,
            "JJA_ANOMALY": anomaly,
        })
        return row


# ==============================================================================
# OPTIMIZED CYCLONE ENGINE — Climatological Risk Assessment (FIXED)
# ==============================================================================

class CycloneRiskEngine(DisasterRiskEngine):
    """
    OPTIMIZED DESIGN: This engine provides a CLIMATOLOGICAL RISK ASSESSMENT.
    
    The user only needs to provide LATITUDE and LONGITUDE. The month is
    automatically detected from the current date.
    
    The model provides:
    1. OCCURRENCE probability: Will a storm form in this location/month?
    2. SEVERITY probability: If it forms, will it become severe?
    3. Combined risk: Overall probability of a severe storm
    """
    hazard_name = "cyclone"
    
    FEATURES = ["LAT", "LON", "DIST2LAND", "USA_WIND", "USA_PRES", "USA_POCI",
                "PRESSURE_DEFICIT", "STORM_SPEED",
                "MONTH_SIN", "MONTH_COS", "DIR_SIN", "DIR_COS"]
    
    _climatology_cache = None
    _monthly_probabilities = None
    _monthly_severity_rates = None
    
    def __init__(self):
        super().__init__()
        self.training_data_path = None
    
    def load_and_engineer(self, path):
        """Returns the fully engineered dataset for the model to train on."""
        self.training_data_path = path
        df = pd.read_excel(path, sheet_name="Sheet1")
        df["GENESIS_MONTH"] = df["SID"].apply(sid_to_month)
        df = df.sort_values("SID")
        
        # Compute monthly occurrence probabilities
        genesis = df.groupby("SID").first().reset_index()
        genesis["GENESIS_MONTH"] = genesis["SID"].apply(sid_to_month)
        genesis["YEAR"] = genesis["SEASON"]
        
        # Monthly occurrence probability (global)
        years = genesis["YEAR"].unique()
        total_years = len(years)
        monthly_counts = genesis.groupby("GENESIS_MONTH").size()
        self._monthly_probabilities = (monthly_counts / total_years).to_dict()
        
        # Compute monthly severity rates
        max_sshs = df.groupby("SID")["USA_SSHS"].max().reset_index()
        max_sshs.columns = ["SID", "MAX_SSHS"]
        max_sshs["SEVERE"] = (max_sshs["MAX_SSHS"] >= 1).astype(int)
        
        severe_by_month = genesis.merge(max_sshs, on="SID")
        monthly_severe = severe_by_month.groupby("GENESIS_MONTH")["SEVERE"].mean()
        self._monthly_severity_rates = monthly_severe.to_dict()
        
        # Get first weak stage for each storm for severity model training
        weak_stage = (df[df["USA_SSHS"] < 1]
                      .sort_values("SID")
                      .groupby("SID", as_index=False)
                      .first())
        
        # Properly merge max_sshs with weak_stage
        weak_stage = weak_stage.merge(max_sshs, on="SID")
        weak_stage["SEVERE"] = (weak_stage["MAX_SSHS"] >= 1).astype(int)
        
        # Engineer the features
        weak_stage = self._engineer(weak_stage)
        
        X = weak_stage[self.FEATURES]
        y = weak_stage["SEVERE"]
        return X, y
    
    @staticmethod
    def _engineer(df):
        df = df.copy()
        df["PRESSURE_DEFICIT"] = df["USA_POCI"] - df["USA_PRES"]
        df["MONTH_SIN"] = np.sin(2 * np.pi * df["GENESIS_MONTH"] / 12)
        df["MONTH_COS"] = np.cos(2 * np.pi * df["GENESIS_MONTH"] / 12)
        df["DIR_SIN"] = np.sin(np.radians(df["STORM_DIR"]))
        df["DIR_COS"] = np.cos(np.radians(df["STORM_DIR"]))
        return df
    
    def _load_climatology(self, data_path):
        """Loads the training data and computes average features for each grid cell and month."""
        if self._climatology_cache is not None:
            return self._climatology_cache
        
        print("Loading cyclone climatology from training data...")
        df = pd.read_excel(data_path, sheet_name="Sheet1")
        df["GENESIS_MONTH"] = df["SID"].apply(sid_to_month)
        df = df.sort_values("SID")
        
        # Get the first weak stage for each storm
        weak_stage = (df[df["USA_SSHS"] < 1]
                      .sort_values("SID")
                      .groupby("SID", as_index=False)
                      .first())
        
        max_sshs = df.groupby("SID")["USA_SSHS"].max().reset_index()
        max_sshs.columns = ["SID", "MAX_SSHS"]
        weak_stage = weak_stage.merge(max_sshs, on="SID")
        
        # Engineer the features
        weak_stage["PRESSURE_DEFICIT"] = weak_stage["USA_POCI"] - weak_stage["USA_PRES"]
        weak_stage["MONTH_SIN"] = np.sin(2 * np.pi * weak_stage["GENESIS_MONTH"] / 12)
        weak_stage["MONTH_COS"] = np.cos(2 * np.pi * weak_stage["GENESIS_MONTH"] / 12)
        weak_stage["DIR_SIN"] = np.sin(np.radians(weak_stage["STORM_DIR"]))
        weak_stage["DIR_COS"] = np.cos(np.radians(weak_stage["STORM_DIR"]))
        
        # Discretize location into grid cells (1 degree resolution)
        weak_stage['LAT_GRID'] = np.floor(weak_stage['LAT']).astype(int)
        weak_stage['LON_GRID'] = np.floor(weak_stage['LON']).astype(int)
        
        # Group by grid cell and month, compute mean for each feature
        feature_cols = self.FEATURES
        climatology = weak_stage.groupby(['LAT_GRID', 'LON_GRID', 'GENESIS_MONTH'], as_index=False)[feature_cols].mean()
        
        # Add helper column for grid cell center
        climatology['LAT'] = climatology['LAT_GRID'] + 0.5
        climatology['LON'] = climatology['LON_GRID'] + 0.5
        
        self._climatology_cache = climatology
        print(f"Climatology loaded: {len(climatology)} grid-cell/month combinations.")
        return climatology
    
    def _get_climatology_row(self, lat: float, lon: float, month: int) -> dict:
        """Builds the feature row using climatological averages for given location and month."""
        if self.training_data_path is None:
            raise RuntimeError("Engine has not been trained. Cannot build climatology.")
        if self._climatology_cache is None:
            self._load_climatology(self.training_data_path)
        
        lat_grid = np.floor(lat).astype(int)
        lon_grid = np.floor(lon).astype(int)
        
        # Try exact match first
        lookup = self._climatology_cache[
            (self._climatology_cache['LAT_GRID'] == lat_grid) &
            (self._climatology_cache['LON_GRID'] == lon_grid) &
            (self._climatology_cache['GENESIS_MONTH'] == month)
        ]
        
        if not lookup.empty:
            row = {col: lookup.iloc[0][col] for col in self.FEATURES}
        else:
            # Try same location, any month
            location_data = self._climatology_cache[
                (self._climatology_cache['LAT_GRID'] == lat_grid) &
                (self._climatology_cache['LON_GRID'] == lon_grid)
            ]
            
            if not location_data.empty:
                # Find nearest month
                location_data['MONTH_DIFF'] = abs(location_data['GENESIS_MONTH'] - month)
                nearest = location_data.loc[location_data['MONTH_DIFF'].idxmin()]
                row = {col: nearest[col] for col in self.FEATURES}
            else:
                # Try same month, any location
                month_data = self._climatology_cache[
                    self._climatology_cache['GENESIS_MONTH'] == month
                ]
                if not month_data.empty:
                    row = {col: month_data[col].mean() for col in self.FEATURES}
                else:
                    # Absolute fallback: use overall averages
                    row = {col: self._climatology_cache[col].mean() for col in self.FEATURES}
        
        # Use the user's actual lat/lon, not the grid center
        row['LAT'] = lat
        row['LON'] = lon
        return row
    
    def predict_risk(self, lat: float, lon: float, month: int = None) -> dict:
        """
        Predict cyclone risk at a location.
        
        Args:
            lat: Latitude
            lon: Longitude
            month: Month (1-12). If None, uses current month.
        
        Returns:
            dict: Complete cyclone risk assessment
        """
        if month is None:
            month = datetime.datetime.now().month
        
        # Get occurrence probability
        occurrence_prob = self._monthly_probabilities.get(month, 0.01) if self._monthly_probabilities else 0.01
        
        # Get severity probability
        climatology_row = self._get_climatology_row(lat, lon, month)
        severity_result = super().predict_risk(climatology_row)
        severity_prob = severity_result["probability"]
        
        # Combined probability: P(occurs AND severe) = P(occurs) * P(severe | occurs)
        combined_prob = occurrence_prob * severity_prob
        
        # Determine if disaster will happen
        will_occur = combined_prob >= 0.5
        
        # Risk category based on combined probability
        risk_score = combined_prob * 100
        
        if risk_score < 5:
            category = "LOW"
            advice = "Very low cyclone risk in this region and month. Routine monitoring sufficient."
        elif risk_score < 15:
            category = "MODERATE"
            advice = "Moderate cyclone risk. Stay aware of seasonal forecasts and official bulletins."
        elif risk_score < 30:
            category = "HIGH"
            advice = "High cyclone risk historically. Review emergency plans and prepare supply kits."
        else:
            category = "SEVERE"
            advice = "Severe cyclone risk historically. Ensure robust preparedness measures and follow local evacuation procedures."
        
        month_name = datetime.date(2024, month, 1).strftime("%B")
        
        return {
            "hazard": "cyclone",
            "month": month,
            "month_name": month_name,
            "occurrence_probability_percent": round(occurrence_prob * 100, 1),
            "severity_probability_if_formed_percent": round(severity_prob * 100, 1),
            "combined_risk_percent": round(combined_prob * 100, 1),
            "risk_score": round(risk_score, 1),
            "risk_category": category,
            "will_occur": will_occur,
            "advice": advice
        }


# ==============================================================================
# EARTHQUAKE ENGINE — Monthly Risk Analysis for India
# ==============================================================================

class EarthquakeRiskEngine(DisasterRiskEngine):
    """
    DESIGN CHOICE: Monthly risk analysis for earthquake-prone regions in India.
    Uses historical patterns to assess risk for any month in any region.
    """
    hazard_name = "earthquake"

    def __init__(self):
        super().__init__()
        self._historical_data = None
        self._region_mapping = None

    def _get_indian_state(self, lat, lon):
        """Map coordinates to Indian regions."""
        if 22 <= lat <= 30 and 88 <= lon <= 97:
            return "Northeast India"
        elif 28 <= lat <= 36 and 72 <= lon <= 85:
            return "Himalayan Region"
        elif 6 <= lat <= 14 and 92 <= lon <= 94:
            return "Andaman & Nicobar Islands"
        elif 22 <= lat <= 25 and 68 <= lon <= 72:
            return "Gujarat (Kutch)"
        elif 10 <= lat <= 20 and 73 <= lon <= 78:
            return "Western Ghats"
        elif 20 <= lat <= 28 and 75 <= lon <= 85:
            return "Central India"
        elif 8 <= lat <= 20 and 75 <= lon <= 80:
            return "Southern India"
        else:
            return "Other"

    def _add_state_column(self, df):
        df['state'] = df.apply(lambda row: self._get_indian_state(row['latitude'], row['longitude']), axis=1)
        return df

    def load_and_engineer(self, path):
        """Load earthquake data and prepare for training."""
        df = pd.read_csv(path)
        df = df[df["type"] == "earthquake"].copy()
        df['time'] = pd.to_datetime(df['time'])
        
        # Add state/region column
        df = self._add_state_column(df)
        
        # Filter for India region
        df = df[df['state'] != 'Other']
        
        # Store for later use
        self._historical_data = df
        
        # For the stacking model, we need to create features
        # We'll use yearly aggregated features for training
        df['year'] = df['time'].dt.year
        df['month'] = df['time'].dt.month
        
        # Aggregate by region and year
        agg = df.groupby(['state', 'year']).agg(
            event_count=('mag', 'count'),
            max_mag=('mag', 'max'),
            mean_mag=('mag', 'mean'),
            mean_depth=('depth', 'mean')
        ).reset_index()
        
        # Get the most active months for each region
        monthly_agg = df.groupby(['state', 'month']).agg(
            month_count=('mag', 'count'),
            month_max_mag=('mag', 'max'),
            month_mean_mag=('mag', 'mean')
        ).reset_index()
        
        # Merge monthly averages into yearly data
        # This is a simplified approach - for a real model we'd want more features
        agg['avg_monthly_count'] = agg['state'].map(
            monthly_agg.groupby('state')['month_count'].mean()
        )
        
        # Create target: Was there a significant earthquake (>=5.0) in the region this year?
        significant = df[df['mag'] >= 5.0]
        sig_by_region_year = significant.groupby(['state', 'year']).size().reset_index(name='sig_count')
        
        agg = agg.merge(sig_by_region_year, on=['state', 'year'], how='left')
        agg['sig_count'] = agg['sig_count'].fillna(0)
        agg['SIGNIFICANT'] = (agg['sig_count'] > 0).astype(int)
        
        # Features for the model
        feature_cols = ['event_count', 'max_mag', 'mean_mag', 'mean_depth', 'avg_monthly_count']
        X = agg[feature_cols].fillna(0)
        y = agg['SIGNIFICANT']
        
        # Store region names for later reference
        self._region_mapping = agg[['state'] + feature_cols + ['SIGNIFICANT']].copy()
        
        return X, y

    def get_top_regions(self, df=None, top_n=5):
        """Get the top N most earthquake-prone regions in India."""
        if df is None and self._historical_data is not None:
            df = self._historical_data
        elif df is None:
            raise ValueError("No data available. Load data first or provide a DataFrame.")
        
        region_counts = df['state'].value_counts()
        top_regions = region_counts.head(top_n)
        return top_regions.to_dict()

    def analyze_monthly_risk(self, month, region, verbose=True):
        """
        Analyzes earthquake risk for a specific month and region.
        
        Args:
            month (int or str): Month (1-12) or month name
            region (str): Region name
            verbose (bool): Whether to print output
            
        Returns:
            dict: Comprehensive risk assessment
        """
        if self._historical_data is None:
            raise RuntimeError("Earthquake data not loaded. Call load_and_engineer first.")
        
        # Parse month
        if isinstance(month, str):
            month_names = ['january', 'february', 'march', 'april', 'may', 'june',
                          'july', 'august', 'september', 'october', 'november', 'december']
            try:
                month_num = month_names.index(month.lower()) + 1
                month_name = month.capitalize()
            except ValueError:
                return {
                    'error': f"Invalid month name: '{month}'.",
                    'risk_level': 'ERROR'
                }
        else:
            month_num = month
            if 1 <= month <= 12:
                month_name = datetime.date(2000, month, 1).strftime('%B')
            else:
                return {
                    'error': f"Invalid month number: {month}. Please use 1-12.",
                    'risk_level': 'ERROR'
                }
        
        # Filter data
        df = self._historical_data
        region_data = df[df['state'] == region]
        monthly_data = region_data[region_data['time'].dt.month == month_num]
        
        if len(monthly_data) == 0:
            return {
                'region': region,
                'month': month_name,
                'month_num': month_num,
                'risk_level': 'INSUFFICIENT_DATA',
                'message': f'No earthquake data available for {region} in {month_name}.',
                'total_earthquakes_region': len(region_data),
                'statistics': {
                    'total_earthquakes_region': len(region_data),
                    'earthquakes_this_month': 0,
                    'average_magnitude_this_month': 0,
                    'max_magnitude_this_month': 0,
                    'min_magnitude_this_month': 0,
                    'magnitude_variability': 0,
                    'frequency_ratio': 0
                },
                'comparison': {
                    'overall_avg_magnitude': 0,
                    'overall_max_magnitude': 0
                },
                'risk_factors': ['Insufficient data for analysis'],
                'recommendation': f'No historical earthquake data available for {region} in {month_name}.'
            }
        
        # Calculate statistics
        hist_count = len(monthly_data)
        hist_avg_mag = monthly_data['mag'].mean()
        hist_max_mag = monthly_data['mag'].max()
        hist_min_mag = monthly_data['mag'].min()
        hist_std_mag = monthly_data['mag'].std()
        
        # Baseline
        all_count = len(region_data)
        all_avg_mag = region_data['mag'].mean() if all_count > 0 else 0
        all_max_mag = region_data['mag'].max() if all_count > 0 else 0
        
        # Calculate risk score
        risk_score = 0
        risk_factors = []
        
        avg_per_month = all_count / 12 if all_count > 0 else 1
        frequency_ratio = hist_count / avg_per_month if avg_per_month > 0 else 0
        
        if frequency_ratio > 2.0:
            risk_score += 0.35
            risk_factors.append(f"This month has {frequency_ratio:.1f}x MORE earthquakes than average in {region}")
        elif frequency_ratio > 1.3:
            risk_score += 0.2
            risk_factors.append(f"This month has {frequency_ratio:.1f}x more earthquakes than average in {region}")
        elif frequency_ratio < 0.5:
            risk_factors.append(f"This month has {frequency_ratio:.1f}x fewer earthquakes than average in {region}")
        
        if hist_max_mag >= 6.5:
            risk_score += 0.3
            risk_factors.append(f"Historical maximum for this month is {hist_max_mag:.1f} (Major earthquake)")
        elif hist_max_mag >= 5.5:
            risk_score += 0.2
            risk_factors.append(f"Historical maximum for this month is {hist_max_mag:.1f} (Strong earthquake)")
        elif hist_max_mag >= 4.5:
            risk_score += 0.1
            risk_factors.append(f"Historical maximum for this month is {hist_max_mag:.1f}")
        
        if hist_std_mag > 0.8:
            risk_score += 0.1
            risk_factors.append(f"High magnitude variability (std: {hist_std_mag:.2f})")
        
        risk_score = min(risk_score, 1.0)
        
        if risk_score >= 0.7:
            risk_level = "HIGH"
        elif risk_score >= 0.4:
            risk_level = "MODERATE"
        elif risk_score >= 0.2:
            risk_level = "LOW"
        else:
            risk_level = "VERY_LOW"
        
        result = {
            'region': region,
            'month': month_name,
            'month_num': month_num,
            'risk_level': risk_level,
            'risk_score': round(risk_score * 100, 1),
            'risk_factors': risk_factors,
            'statistics': {
                'total_earthquakes_region': all_count,
                'earthquakes_this_month': hist_count,
                'average_magnitude_this_month': round(hist_avg_mag, 2),
                'max_magnitude_this_month': round(hist_max_mag, 2),
                'min_magnitude_this_month': round(hist_min_mag, 2),
                'magnitude_variability': round(hist_std_mag, 2),
                'frequency_ratio': round(frequency_ratio, 2)
            },
            'comparison': {
                'overall_avg_magnitude': round(all_avg_mag, 2),
                'overall_max_magnitude': round(all_max_mag, 2)
            },
            'recommendation': self._get_recommendation(risk_level, region, month_name)
        }
        
        if verbose:
            self._print_monthly_analysis(result)
        
        return result
    
    def _get_recommendation(self, risk_level, region, month):
        if risk_level == "HIGH":
            return f"HIGH ALERT for {region} in {month}: This is historically an active period. Ensure emergency kits are stocked, review evacuation routes, and stay informed about seismic activity."
        elif risk_level == "MODERATE":
            return f"MODERATE ALERT for {region} in {month}: Stay vigilant. Review your earthquake preparedness plan. Secure heavy furniture and have a communication plan."
        elif risk_level == "LOW":
            return f"LOW RISK for {region} in {month}: Continue regular preparedness. Good time to review your emergency supplies."
        else:
            return f"VERY LOW RISK for {region} in {month}: No immediate concerns. Continue normal preparedness."

    def _print_monthly_analysis(self, assessment):
        if assessment.get('risk_level') == 'ERROR':
            print(f"\nERROR: {assessment.get('error', 'Unknown error occurred')}")
            return
        
        if assessment.get('risk_level') == 'INSUFFICIENT_DATA':
            print(f"\nINSUFFICIENT DATA: {assessment.get('message', '')}")
            print(f"Total earthquakes in region: {assessment.get('total_earthquakes_region', 0)}")
            return
        
        print("\n" + "="*70)
        print("EARTHQUAKE RISK ASSESSMENT")
        print("="*70)
        print(f"Region: {assessment['region']}")
        print(f"Month: {assessment['month']}")
        print(f"Risk Level: {assessment['risk_level']} (Score: {assessment['risk_score']}%)")
        print("="*70)
        
        print("\nHISTORICAL STATISTICS:")
        print(f"  Total Earthquakes in Region: {assessment['statistics']['total_earthquakes_region']}")
        print(f"  Earthquakes in {assessment['month']}: {assessment['statistics']['earthquakes_this_month']}")
        print(f"  Average Magnitude ({assessment['month']}): {assessment['statistics']['average_magnitude_this_month']}")
        print(f"  Maximum Magnitude ({assessment['month']}): {assessment['statistics']['max_magnitude_this_month']}")
        print(f"  Minimum Magnitude ({assessment['month']}): {assessment['statistics']['min_magnitude_this_month']}")
        print(f"  Magnitude Variability: {assessment['statistics']['magnitude_variability']}")
        
        print("\nCOMPARISON:")
        print(f"  Overall Average Magnitude: {assessment['comparison']['overall_avg_magnitude']}")
        print(f"  Overall Maximum Magnitude: {assessment['comparison']['overall_max_magnitude']}")
        
        print("\nRISK FACTORS:")
        if assessment['risk_factors']:
            for factor in assessment['risk_factors']:
                print(f"  - {factor}")
        else:
            print("  - No significant risk factors identified.")
        
        print("\nRECOMMENDATION:")
        print(f"  {assessment['recommendation']}")
        print("\n" + "="*70)

    def predict_risk(self, feature_row: dict) -> dict:
        """
        Override to handle the monthly risk analysis format.
        """
        # If it's a monthly risk request
        if 'month' in feature_row and 'region' in feature_row:
            return self.analyze_monthly_risk(
                feature_row['month'], 
                feature_row['region'],
                verbose=False
            )
        # Otherwise use the base predict_risk
        return super().predict_risk(feature_row)


# ==============================================================================
# GOOGLE WEATHER API NOWCAST — a separate, RULE-BASED short-term layer
# ==============================================================================

import requests


class GoogleWeatherNowcast:
    """Short-term (10-day) rainfall nowcast using the Google Maps Platform
    Weather API, checked against a configurable FLOOD THRESHOLD."""

    FORECAST_URL = "https://weather.googleapis.com/v1/forecast/days:lookup"
    DEFAULT_FLOOD_THRESHOLD_MM = 204.0

    def __init__(self, api_key: str, flood_threshold_mm: float = None):
        self.api_key = api_key
        self.flood_threshold_mm = (
            flood_threshold_mm if flood_threshold_mm is not None
            else self.DEFAULT_FLOOD_THRESHOLD_MM
        )

    def fetch_10day_precip_forecast(self, lat: float, lon: float) -> list:
        params = {
            "key": self.api_key,
            "location.latitude": lat,
            "location.longitude": lon,
            "days": 10,
        }
        resp = requests.get(self.FORECAST_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        daily_precip = []
        for day in data.get("forecastDays", []):
            mm_today = 0.0
            for part_key in ("daytimeForecast", "nighttimeForecast"):
                part = day.get(part_key, {})
                qty = part.get("precipitation", {}).get("qpf", {}).get("quantity")
                if qty is not None:
                    mm_today += float(qty)
            daily_precip.append(mm_today)
        return daily_precip

    def check_this_month(self, lat: float, lon: float, month_name: str) -> dict:
        forecast_mm = self.fetch_10day_precip_forecast(lat, lon)
        forecast_total = sum(forecast_mm)

        will_flood = forecast_total >= self.flood_threshold_mm

        return {
            "month": month_name,
            "forecast_10day_total_mm": round(forecast_total, 1),
            "flood_threshold_mm": self.flood_threshold_mm,
            "flood_expected_this_month": will_flood,
        }


# ==============================================================================
# ORCHESTRATOR — trains/holds every hazard engine, produces a combined report
# ==============================================================================

class MultiDisasterRiskSystem:
    def __init__(self):
        self.engines = {
            "flood": FloodRiskEngine(),
            "cyclone": CycloneRiskEngine(),
            "earthquake": EarthquakeRiskEngine(),
        }
        self.nowcast = None

    def train_all(self, flood_path, cyclone_path, earthquake_path):
        self.engines["flood"].train(flood_path)
        self.engines["cyclone"].train(cyclone_path)
        self.engines["earthquake"].train(earthquake_path, test_size=0.2)
        for engine in self.engines.values():
            engine.save()

    def setup_nowcast(self, api_key: str, flood_threshold_mm: float = None):
        self.nowcast = GoogleWeatherNowcast(api_key, flood_threshold_mm)

    def flood_nowcast(self, lat: float, lon: float, month_name: str) -> dict:
        if self.nowcast is None:
            raise RuntimeError("Call setup_nowcast(api_key) first.")
        return self.nowcast.check_this_month(lat, lon, month_name)

    def flood_risk(self, monthly_rainfall: dict) -> dict:
        engine = self.engines["flood"]
        row = engine.build_input(monthly_rainfall)
        return engine.predict_risk(row)

    def cyclone_risk(self, lat: float, lon: float, month: int = None) -> dict:
        """Complete cyclone risk assessment requiring only latitude and longitude.
        Month is automatically detected from current date if not provided."""
        engine = self.engines["cyclone"]
        return engine.predict_risk(lat, lon, month)

    def earthquake_risk(self, month, region) -> dict:
        """Monthly earthquake risk assessment for a region."""
        engine = self.engines["earthquake"]
        return engine.analyze_monthly_risk(month, region, verbose=False)

    def earthquake_top_regions(self, top_n=5) -> dict:
        """Get the top earthquake-prone regions in India."""
        engine = self.engines["earthquake"]
        if engine._historical_data is None:
            raise RuntimeError("Earthquake data not loaded. Train the system first.")
        return engine.get_top_regions(top_n=top_n)

    def combined_report(self, monthly_rainfall: dict = None, 
                        cyclone_lat: float = None, cyclone_lon: float = None,
                        cyclone_month: int = None,
                        earthquake_month=None, earthquake_region=None) -> dict:
        """Produce a unified multi-hazard risk report. Any input can be omitted."""
        report = {}
        scores = []

        if monthly_rainfall is not None:
            report["flood"] = self.flood_risk(monthly_rainfall)
            scores.append(report["flood"]["risk_score"])

        if cyclone_lat is not None and cyclone_lon is not None:
            report["cyclone"] = self.cyclone_risk(cyclone_lat, cyclone_lon, cyclone_month)
            scores.append(report["cyclone"]["risk_score"])

        if earthquake_month is not None and earthquake_region is not None:
            report["earthquake"] = self.earthquake_risk(earthquake_month, earthquake_region)
            scores.append(report["earthquake"]["risk_score"])

        if scores:
            overall = max(scores)
            report["overall_regional_risk_index"] = round(overall, 1)
            report["overall_regional_risk_category"] = risk_category(overall / 100)["risk_category"]

        return report

    @staticmethod
    def print_report(report: dict):
        print("\n" + "=" * 60)
        print(" MULTI-HAZARD RISK REPORT")
        print("=" * 60)
        for hazard in ("flood", "cyclone", "earthquake"):
            if hazard in report:
                r = report[hazard]
                if hazard == "cyclone":
                    print(f"\n[{hazard.upper()}] (climatological risk assessment)")
                    print(f"  Month assessed                : {r['month_name']} ({r['month']})")
                    print(f"  Genesis probability (this month): {r['occurrence_probability_percent']}%")
                    print(f"  Severity probability if formed : {r['severity_probability_if_formed_percent']}%")
                    print(f"  Combined risk probability      : {r['combined_risk_percent']}%")
                    print(f"  Risk score (0-100)            : {r['risk_score']}")
                    print(f"  Risk category                 : {r['risk_category']}")
                    print(f"  Guidance                      : {r['advice']}")
                elif hazard == "earthquake":
                    print(f"\n[{hazard.upper()}] (monthly risk assessment)")
                    print(f"  Region                        : {r['region']}")
                    print(f"  Month assessed                : {r['month']}")
                    print(f"  Risk score (0-100)            : {r['risk_score']}")
                    print(f"  Risk category                 : {r['risk_level']}")
                    print(f"  Earthquakes this month        : {r['statistics']['earthquakes_this_month']}")
                    print(f"  Average magnitude this month  : {r['statistics']['average_magnitude_this_month']}")
                    print(f"  Maximum magnitude this month  : {r['statistics']['max_magnitude_this_month']}")
                    print(f"  Guidance                      : {r['recommendation']}")
                else:
                    occur = "YES" if r["will_occur"] else "NO (unlikely)"
                    print(f"\n[{hazard.upper()}] (seasonal ML model)")
                    print(f"  Predicted to occur this year : {occur}")
                    print(f"  Risk score (0-100)            : {r['risk_score']}")
                    print(f"  Risk category                 : {r['risk_category']}")
                    print(f"  Guidance                      : {r['advice']}")
        if "nowcast" in report:
            n = report["nowcast"]
            answer = "YES" if n["flood_expected_this_month"] else "NO"
            print(f"\n[SHORT-TERM NOWCAST] (rule-based, Google Weather API, next 10 days)")
            print(f"  Month checked                 : {n['month']}")
            print(f"  Forecasted 10-day rainfall     : {n['forecast_10day_total_mm']} mm")
            print(f"  Flood threshold (configurable) : {n['flood_threshold_mm']} mm")
            print(f"  Will flood happen this month?  : {answer}")
        if "overall_regional_risk_index" in report:
            print(f"\n>>> OVERALL REGIONAL RISK INDEX : {report['overall_regional_risk_index']}"
                  f"  [{report['overall_regional_risk_category']}]")
        print("=" * 60 + "\n")


# ==============================================================================
# INTERACTIVE CLI
# ==============================================================================

def _prompt_float(msg, default=0.0):
    raw = input(f"{msg} [{default}]: ").strip()
    return float(raw) if raw else default


def _prompt_int(msg, default=0):
    raw = input(f"{msg} [{default}]: ").strip()
    return int(raw) if raw else default


def run_flood_interview(system: MultiDisasterRiskSystem):
    print("\nEnter this year's monsoon rainfall (mm, Jun-Aug -- matches IMD's")
    print("Subdivision-wise Rainfall Distribution report). Press Enter for 0.")
    monthly = {}
    for m in FloodRiskEngine.MONTHS:
        monthly[m] = _prompt_float(f"  {m}")
    result = system.flood_risk(monthly)
    return monthly, result


def run_cyclone_interview(system: MultiDisasterRiskSystem):
    print("\nEnter the location for cyclone risk assessment.")
    print("The system will automatically use the current month.")
    lat = _prompt_float("  Latitude (e.g., 12.9 for Mangaluru)", 12.9)
    lon = _prompt_float("  Longitude (e.g., 74.8)", 74.8)
    
    # Ask if they want to specify a different month
    use_specific_month = input("  Specify a different month? (y/n) [n]: ").strip().lower() == 'y'
    if use_specific_month:
        month = _prompt_int("  Month (1-12)", datetime.datetime.now().month)
    else:
        month = None
    
    result = system.cyclone_risk(lat, lon, month)
    return {"lat": lat, "lon": lon, "month": result.get("month")}, result


def run_earthquake_interview(system: MultiDisasterRiskSystem):
    print("\nEnter the region for earthquake risk assessment.")
    
    # Show top regions first
    try:
        top_regions = system.earthquake_top_regions(5)
        print("\nTop Earthquake-Prone Regions:")
        region_list = list(top_regions.keys())
        for i, region in enumerate(region_list, 1):
            print(f"  {i}. {region} ({top_regions[region]} earthquakes)")
    except:
        region_list = ["Northeast India", "Andaman & Nicobar Islands", "Himalayan Region"]
        print("\nKnown Earthquake-Prone Regions:")
        for i, region in enumerate(region_list, 1):
            print(f"  {i}. {region}")
    
    print("\nEnter region name or number from list:")
    region_input = input("  Region: ").strip()
    if region_input.isdigit():
        idx = int(region_input) - 1
        if 0 <= idx < len(region_list):
            region = region_list[idx]
        else:
            region = region_list[0]
    else:
        region = region_input
    
    month_input = input("  Month (1-12 or month name, e.g., 'October'): ").strip()
    if month_input.isdigit():
        month = int(month_input)
    else:
        month = month_input
    
    result = system.earthquake_risk(month, region)
    return {"month": month, "region": region}, result


def run_nowcast_interview(system: MultiDisasterRiskSystem):
    print("\nLive short-term rainfall check (Google Weather API, next 10 days).")
    if system.nowcast is None:
        api_key = os.getenv("GOOGLE_MAPS_API_KEY")
        if not api_key:
            print("  GOOGLE_MAPS_API_KEY is not set in the environment / .env file.")
            return {"error": "missing_api_key", "flood_expected_this_month": False}
        threshold = 204.0
        print(f"  Flood threshold, mm over 10 days (DUMMY value for now): {threshold}")
        system.setup_nowcast(api_key, flood_threshold_mm=threshold)

    lat, lon = 12.9141, 74.8560
    print(f"  Location: Coastal Karnataka (Mangaluru) -- Lat {lat}, Lon {lon}")
    current_month_name = datetime.date.today().strftime("%b").upper()
    print(f"  (Note: this checks the real next 10 days from today, i.e. {current_month_name}.)")
    result = system.flood_nowcast(lat, lon, current_month_name)
    return result


def main():
    system = MultiDisasterRiskSystem()

    flood_path = "data/rainfall.xlsx"
    cyclone_path = "data/Cyclone_Dataset.xlsx"
    earthquake_path = "data/Earthquakes.csv"

    print("Training multi-disaster risk models (Flood + Cyclone + Earthquake stacking ensembles)...")
    system.train_all(flood_path, cyclone_path, earthquake_path)

    while True:
        print("\n--- MULTI-DISASTER RISK MENU ---")
        print("1. Assess Flood risk (seasonal ML model)")
        print("2. Assess Cyclone risk (climatological risk assessment)")
        print("3. Assess Earthquake risk (monthly risk assessment)")
        print("4. Combined multi-hazard assessment (all three)")
        print("5. Live short-term flood nowcast (Google Weather API)")
        print("6. Exit")
        choice = input("Choose an option: ").strip()

        if choice == "1":
            _, result = run_flood_interview(system)
            system.print_report({"flood": result})
        elif choice == "2":
            _, result = run_cyclone_interview(system)
            system.print_report({"cyclone": result})
        elif choice == "3":
            _, result = run_earthquake_interview(system)
            system.print_report({"earthquake": result})
        elif choice == "4":
            monthly, _ = run_flood_interview(system)
            print("\n--- Cyclone Risk Input ---")
            cyclone_lat = _prompt_float("  Latitude", 12.9)
            cyclone_lon = _prompt_float("  Longitude", 74.8)
            use_specific_month = input("  Specify a different month? (y/n) [n]: ").strip().lower() == 'y'
            if use_specific_month:
                cyclone_month = _prompt_int("  Month (1-12)", datetime.datetime.now().month)
            else:
                cyclone_month = None
            print("\n--- Earthquake Risk Input ---")
            eq_month = input("  Month (1-12 or name, e.g., 'October'): ").strip()
            if eq_month.isdigit():
                eq_month = int(eq_month)
            # We'll let the earthquake interview handle region selection
            print("\nTop Earthquake-Prone Regions:")
            try:
                top_regions = system.earthquake_top_regions(5)
                region_list = list(top_regions.keys())
                for i, region in enumerate(region_list, 1):
                    print(f"  {i}. {region} ({top_regions[region]} earthquakes)")
            except:
                region_list = ["Northeast India", "Andaman & Nicobar Islands", "Himalayan Region"]
                for i, region in enumerate(region_list, 1):
                    print(f"  {i}. {region}")
            eq_region = input("  Enter region name or number: ").strip()
            if eq_region.isdigit():
                idx = int(eq_region) - 1
                if 0 <= idx < len(region_list):
                    eq_region = region_list[idx]
            report = system.combined_report(
                monthly_rainfall=monthly,
                cyclone_lat=cyclone_lat,
                cyclone_lon=cyclone_lon,
                cyclone_month=cyclone_month,
                earthquake_month=eq_month,
                earthquake_region=eq_region
            )
            system.print_report(report)
        elif choice == "5":
            try:
                nowcast_result = run_nowcast_interview(system)
                system.print_report({"nowcast": nowcast_result})
            except Exception as e:
                print(f"Nowcast check failed: {e}")
        elif choice == "6":
            print("Exiting. Stay safe!")
            break
        else:
            print("Invalid option, try again.")


if __name__ == "__main__":
    main()