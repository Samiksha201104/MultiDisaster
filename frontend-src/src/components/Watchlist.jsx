import React, { useEffect, useState } from 'react';
import { catColorVar } from '../api.js';

const HAZARD_ICON = {
  flood: (
    <svg viewBox="0 0 24 24" fill="none" stroke="var(--blue)" strokeWidth="1.8">
      <path d="M2 15c1.5 1.6 3 1.6 4.5 0s3-1.6 4.5 0 3 1.6 4.5 0 3-1.6 4.5 0" />
      <path d="M2 19c1.5 1.6 3 1.6 4.5 0s3-1.6 4.5 0 3 1.6 4.5 0 3-1.6 4.5 0" />
      <path d="M12 3v8" />
    </svg>
  ),
  cyclone: (
    <svg viewBox="0 0 24 24" fill="none" stroke="var(--violet)" strokeWidth="1.7">
      <path d="M12 12c3-4 7-2 7 1a4 4 0 0 1-4 4" />
      <path d="M12 12c-3 4-7 2-7-1a4 4 0 0 1 4-4" />
      <circle cx="12" cy="12" r="1.4" fill="var(--violet)" stroke="none" />
    </svg>
  ),
  earthquake: (
    <svg viewBox="0 0 24 24" fill="none" stroke="var(--rust)" strokeWidth="1.8">
      <path d="M2 12h4l2-6 3 12 3-9 2 3h6" />
    </svg>
  ),
};

function SiteCard({ site, reading }) {
  const [flash, setFlash] = useState(false);
  const key = reading ? `${reading.score}-${reading.category}-${reading.ts}` : null;

  useEffect(() => {
    if (!key) return;
    setFlash(true);
    const t = setTimeout(() => setFlash(false), 1200);
    return () => clearTimeout(t);
  }, [key]);

  return (
    <div className={`watch-card ${flash ? 'flash' : ''}`}>
      <div className="site-icon">{HAZARD_ICON[site.hazard] || null}</div>
      <div className="site-name">{site.name}</div>
      <div className="site-hazard">{site.hazard}</div>
      <div className="site-read">
        <span className="site-score">{reading ? Number(reading.score).toFixed(1) : '—'}</span>
        <span className="site-cat" style={{ color: reading ? catColorVar(reading.category) : 'var(--text-faint)' }}>
          {reading ? reading.category : 'PENDING'}
        </span>
      </div>
    </div>
  );
}

export default function Watchlist({ sites, readings }) {
  return (
    <section className="panel" style={{ marginBottom: 16 }}>
      <div className="panel-head">
        <h2>
          <span className="n">03</span> Real-Time Watchlist
        </h2>
      </div>
      <div className="panel-body">
        <div className="watch-grid">
          {sites.map((site) => (
            <SiteCard key={site.id} site={site} reading={readings[site.id]} />
          ))}
        </div>
      </div>
    </section>
  );
}
