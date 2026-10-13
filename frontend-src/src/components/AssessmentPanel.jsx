import React, { useState } from 'react';
import { api, fmtINR, catColorVar, catClass } from '../api.js';

const HAZARDS = [
  { id: 'multi', label: 'Multi-Hazard' },
  { id: 'flood', label: 'Flood' },
  { id: 'cyclone', label: 'Cyclone' },
  { id: 'earthquake', label: 'Earthquake' },
];

const EQ_REGIONS = [
  'Northeast India',
  'Himalayan Region',
  'Andaman & Nicobar Islands',
  'Gujarat (Kutch)',
  'Western Ghats',
  'Central India',
  'Southern India',
];

export default function AssessmentPanel({ onAssessed }) {
  const [hazard, setHazard] = useState('multi');
  const [region, setRegion] = useState('Coastal Karnataka');
  const [rainfall, setRainfall] = useState({ JUN: 280, JUL: 420, AUG: 310 });
  const [lat, setLat] = useState(12.9141);
  const [lon, setLon] = useState(74.856);
  const [month, setMonth] = useState('');
  const [eqRegion, setEqRegion] = useState('Northeast India');
  const [eqMonth, setEqMonth] = useState(8);
  const [autoDisburse, setAutoDisburse] = useState(true);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState(null);

  const showRainfall = hazard === 'multi' || hazard === 'flood';
  const showGeo = hazard === 'multi' || hazard === 'cyclone';
  const showEq = hazard === 'multi' || hazard === 'earthquake';

  async function runAssessment() {
    setLoading(true);
    setError('');
    try {
      const body = {
        region: region || 'Coastal Karnataka',
        hazard,
        auto_disburse: autoDisburse,
        lat: parseFloat(lat),
        lon: parseFloat(lon),
        month: month ? parseInt(month, 10) : null,
        eq_region: eqRegion,
        eq_month: eqMonth ? parseInt(eqMonth, 10) : null,
        rainfall: {
          JUN: parseFloat(rainfall.JUN) || 0,
          JUL: parseFloat(rainfall.JUL) || 0,
          AUG: parseFloat(rainfall.AUG) || 0,
        },
      };
      const data = await api.assess(body);
      setResult(data);
      onAssessed(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>
          <span className="n">01</span> Run Hazard Assessment
        </h2>
      </div>
      <div className="panel-body">
        {error && <div className="error-banner">{error}</div>}

        <div className="tabs">
          {HAZARDS.map((h) => (
            <button
              key={h.id}
              className={`tab ${hazard === h.id ? 'active' : ''}`}
              onClick={() => setHazard(h.id)}
              type="button"
            >
              {h.label}
            </button>
          ))}
        </div>

        {showRainfall && (
          <div className="field-row">
            <div className="field">
              <label htmlFor="fJun">Rainfall Jun (mm)</label>
              <input
                id="fJun"
                type="number"
                value={rainfall.JUN}
                onChange={(e) => setRainfall({ ...rainfall, JUN: e.target.value })}
              />
            </div>
            <div className="field">
              <label htmlFor="fJul">Rainfall Jul (mm)</label>
              <input
                id="fJul"
                type="number"
                value={rainfall.JUL}
                onChange={(e) => setRainfall({ ...rainfall, JUL: e.target.value })}
              />
            </div>
            <div className="field">
              <label htmlFor="fAug">Rainfall Aug (mm)</label>
              <input
                id="fAug"
                type="number"
                value={rainfall.AUG}
                onChange={(e) => setRainfall({ ...rainfall, AUG: e.target.value })}
              />
            </div>
          </div>
        )}

        {showGeo && (
          <>
            <div className="field-row two">
              <div className="field">
                <label htmlFor="fLat">Latitude</label>
                <input id="fLat" type="number" step="0.0001" value={lat} onChange={(e) => setLat(e.target.value)} />
              </div>
              <div className="field">
                <label htmlFor="fLon">Longitude</label>
                <input id="fLon" type="number" step="0.0001" value={lon} onChange={(e) => setLon(e.target.value)} />
              </div>
            </div>
            <div className="field-row one">
              <div className="field">
                <label htmlFor="fMonth">Month (cyclone, 1&ndash;12, blank = current)</label>
                <input
                  id="fMonth"
                  type="number"
                  min="1"
                  max="12"
                  placeholder="e.g. 11"
                  value={month}
                  onChange={(e) => setMonth(e.target.value)}
                />
              </div>
            </div>
          </>
        )}

        {showEq && (
          <div className="field-row two">
            <div className="field">
              <label htmlFor="fEqRegion">Seismic zone</label>
              <select id="fEqRegion" value={eqRegion} onChange={(e) => setEqRegion(e.target.value)}>
                {EQ_REGIONS.map((r) => (
                  <option key={r}>{r}</option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="fEqMonth">Month (1&ndash;12)</label>
              <input
                id="fEqMonth"
                type="number"
                min="1"
                max="12"
                value={eqMonth}
                onChange={(e) => setEqMonth(e.target.value)}
              />
            </div>
          </div>
        )}

        <div className="toggle-row">
          <div className="txt">
            <b>Auto-disburse</b> &mdash; release funds automatically when the smart contract threshold is met
          </div>
          <label className="switch">
            <input type="checkbox" checked={autoDisburse} onChange={(e) => setAutoDisburse(e.target.checked)} />
            <span className="slider" />
          </label>
        </div>

        <button className="btn" onClick={runAssessment} disabled={loading}>
          {loading ? 'Running…' : 'Run Assessment'}
        </button>

        {result && <ResultView data={result} />}
      </div>
    </div>
  );
}

function ResultView({ data }) {
  const norm = data.allocation.normalized;
  const decision = data.allocation.decision;
  const markerLeft = Math.max(0, Math.min(100, norm.risk_score));

  return (
    <div className="result">
      <div className="gauge-head">
        <div className="gauge-score" style={{ color: catColorVar(norm.risk_category) }}>
          {norm.risk_score.toFixed(1)}
        </div>
        <div className={`gauge-cat ${catClass(norm.risk_category)}`}>{norm.risk_category}</div>
      </div>
      <div className="threshold-bar">
        <span className="tb-low" />
        <span className="tb-mod" />
        <span className="tb-high" />
        <span className="tb-sev" />
        <div className="marker" style={{ left: `${markerLeft}%` }} />
      </div>
      <div className="threshold-labels">
        <span>0</span>
        <span>LOW (0-25)</span>
        <span>MODERATE (25-50)</span>
        <span>HIGH (50-75)</span>
        <span>SEVERE (75-100)</span>
        <span>100</span>
      </div>
      <div className="advice">{norm.advice || ''}</div>
      <div className="decision-row">
        <div>
          <div className="d-label">Contract decision</div>
          <div className={`d-status ${decision.status || ''}`}>{(decision.status || '—').toUpperCase()}</div>
        </div>
        <div className="d-amount">{decision.amount ? fmtINR(decision.amount) : '—'}</div>
        <div className="d-reason">{decision.reason || ''}</div>
      </div>
    </div>
  );
}
