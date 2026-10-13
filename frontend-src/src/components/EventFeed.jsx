import React, { useEffect, useRef } from 'react';
import { fmtINR, fmtTime } from '../api.js';

function describeEvent(evt) {
  const kind = evt.kind || 'system';
  switch (kind) {
    case 'disbursal':
      return (
        <>
          Disbursed <b>{fmtINR(evt.decision?.amount)}</b> to {evt.region || ''} ({evt.hazard}, {evt.risk?.risk_category || ''})
        </>
      );
    case 'assessment':
      return (
        <>
          Assessment held for {evt.region || ''} ({evt.hazard}, score {evt.risk?.risk_score ?? '—'})
        </>
      );
    case 'monitor':
      return (
        <>
          Watchlist pulse &middot; {evt.site?.name || ''} &rarr; {evt.category || 'reading'} ({evt.score ?? '—'})
        </>
      );
    case 'deposit':
      return (
        <>
          Treasury deposit of <b>{fmtINR(evt.amount)}</b> received
        </>
      );
    case 'nowcast':
      return (
        <>
          10-day nowcast for {evt.region || ''}: <b>{evt.forecast_mm ?? '—'}mm</b> vs {evt.threshold_mm ?? '—'}mm threshold
          {evt.flood_expected ? ' — flood likely' : ''}
        </>
      );
    case 'system':
      return evt.message || 'system event';
    case 'hello':
      return `Stream connected · engine ${evt.mode || ''}`;
    default:
      return JSON.stringify(evt);
  }
}

export default function EventFeed({ events, onClear }) {
  const feedRef = useRef(null);

  useEffect(() => {
    const el = feedRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [events.length]);

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>
          <span className="n">02</span> Live Event Feed
        </h2>
        <button className="btn-ghost" onClick={onClear} type="button">
          Clear
        </button>
      </div>
      <div className="panel-body">
        <div className="feed" ref={feedRef}>
          {events.length === 0 && <div className="feed-empty">Waiting for the first event…</div>}
          {events.map((evt, i) => {
            const kind = evt.kind || 'system';
            return (
              <div className="feed-line" key={i}>
                <span className="feed-time">{fmtTime(evt.ts)}</span>
                <span className={`feed-tag tag-${kind}`}>{kind}</span>
                <span className="feed-msg">{describeEvent(evt)}</span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
