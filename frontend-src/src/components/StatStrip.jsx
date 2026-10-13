import React from 'react';
import { fmtINR } from '../api.js';

export default function StatStrip({ treasury }) {
  const t = treasury || {};
  return (
    <section className="stat-strip">
      <div className="stat">
        <div className="label">Treasury</div>
        <div className="value amber">{fmtINR(t.treasury)}</div>
      </div>
      <div className="stat">
        <div className="label">Total Disbursed</div>
        <div className="value">{fmtINR(t.total_disbursed)}</div>
      </div>
      <div className="stat">
        <div className="label">Payouts Executed</div>
        <div className="value">{t.payout_count ?? '—'}</div>
      </div>
      {/* <div className="stat">
        <div className="label">High Threshold</div>
        <div className="value teal">{t.high_threshold ?? '—'}</div>
      </div>
      <div className="stat">
        <div className="label">Severe Threshold</div>
        <div className="value teal">{t.severe_threshold ?? '—'}</div>
      </div> */}
    </section>
  );
}
