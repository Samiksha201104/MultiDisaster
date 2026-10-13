import React, { useState } from 'react';
import { api, catColorVar, catClass } from '../api.js';

const SITES = [
  { name: 'Mangaluru, Coastal Karnataka', lat: 12.9141, lon: 74.8560 },
  { name: 'Mumbai', lat: 19.0760, lon: 72.8777 },
  { name: 'Chennai', lat: 13.0827, lon: 80.2707 },
  { name: 'Kolkata', lat: 22.5726, lon: 88.3639 },
  { name: 'Kochi', lat: 9.9312, lon: 76.2673 },
];

export default function NowcastPanel() {
  const [siteIdx, setSiteIdx] = useState(0);
  const [useCustom, setUseCustom] = useState(false);
  const [customLat, setCustomLat] = useState('');
  const [customLon, setCustomLon] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState(null);

  async function runCheck() {
    setError('');
    const lat = useCustom ? parseFloat(customLat) : SITES[siteIdx].lat;
    const lon = useCustom ? parseFloat(customLon) : SITES[siteIdx].lon;
    const region = useCustom ? `${lat}, ${lon}` : SITES[siteIdx].name;

    if (Number.isNaN(lat) || Number.isNaN(lon)) {
      setError('Enter a valid latitude and longitude.');
      return;
    }

    setLoading(true);
    try {
      const data = await api.nowcast({ lat, lon, region });
      setResult(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="panel" style={{ marginBottom: 16 }}>
      <div className="panel-head">
        <h2>
          <span className="n">02</span> Short-Term Flood Nowcast
        </h2>
        <span style={{ fontSize: 12, opacity: 0.6 }}>Google Weather &middot; next 10 days</span>
      </div>
      <div className="panel-body">
        {error && <div className="error-banner">{error}</div>}

        <div className="field-row one">
          <div className="field">
            <label htmlFor="nSite">Site</label>
            <select
              id="nSite"
              value={useCustom ? 'custom' : siteIdx}
              onChange={(e) => {
                if (e.target.value === 'custom') {
                  setUseCustom(true);
                } else {
                  setUseCustom(false);
                  setSiteIdx(Number(e.target.value));
                }
              }}
            >
              {SITES.map((s, i) => (
                <option key={s.name} value={i}>
                  {s.name}
                </option>
              ))}
              <option value="custom">Custom coordinates&hellip;</option>
            </select>
          </div>
        </div>

        {useCustom && (
          <div className="field-row two">
            <div className="field">
              <label htmlFor="nLat">Latitude</label>
              <input
                id="nLat"
                type="number"
                step="0.0001"
                value={customLat}
                onChange={(e) => setCustomLat(e.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="nLon">Longitude</label>
              <input
                id="nLon"
                type="number"
                step="0.0001"
                value={customLon}
                onChange={(e) => setCustomLon(e.target.value)}
              />
            </div>
          </div>
        )}

        <button className="btn" onClick={runCheck} disabled={loading} type="button">
          {loading ? 'Checking forecast…' : 'Check 10-day forecast'}
        </button>

        {result && <NowcastResult data={result} />}
      </div>
    </section>
  );
}

function NowcastResult({ data }) {
  if (data.error) {
    return <div className="error-banner" style={{ marginTop: 12 }}>{data.error}</div>;
  }

  const category = data.flood_expected_this_month ? 'SEVERE' : 'LOW';
  const pct = data.flood_threshold_mm
    ? Math.max(0, Math.min(100, (data.forecast_10day_total_mm / data.flood_threshold_mm) * 100))
    : 0;

  return (
    <div className="result" style={{ marginTop: 14 }}>
      <div className="gauge-head">
        <div className="gauge-score" style={{ color: catColorVar(category) }}>
          {data.forecast_10day_total_mm} mm
        </div>
        <div className={`gauge-cat ${catClass(category)}`}>
          {data.flood_expected_this_month ? 'FLOOD LIKELY' : 'BELOW THRESHOLD'}
        </div>
      </div>
      <div className="threshold-bar">
        <span className="tb-low" />
        <span className="tb-mod" />
        <span className="tb-high" />
        <span className="tb-sev" />
        <div className="marker" style={{ left: `${pct}%` }} />
      </div>
      <div className="threshold-labels">
        <span>0 mm</span>
        <span>{data.flood_threshold_mm} mm threshold</span>
      </div>
      <div className="advice">
        Forecast window checked in {data.month}: {data.forecast_10day_total_mm}mm of rain expected over the
        next 10 days, against a {data.flood_threshold_mm}mm flood threshold. This is an early-warning signal
        only &mdash; it does not trigger fund disbursal on its own.
      </div>
    </div>
  );
}
