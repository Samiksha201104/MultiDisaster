import React, { useEffect, useState } from 'react';

export default function Header({ engineMode, chainInfo }) {
  const [clock, setClock] = useState(new Date());

  useEffect(() => {
    const id = setInterval(() => setClock(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  const chainOk = chainInfo && chainInfo.valid;

  return (
    <header className="command-bar">
      <div className="brand">
        <div className="brand-mark">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
            <path d="M12 2 3 6v6c0 5 3.8 8.7 9 10 5.2-1.3 9-5 9-10V6l-9-4Z" />
            <path d="M9 12.2l2 2 4-4.2" />
          </svg>
        </div>
        <div>
          <h1>National Disaster Relief Command</h1>
          <p>Smart Fund Allocation &mdash; oracle-linked treasury, tamper-evident ledger</p>
        </div>
      </div>
      <div className="status-cluster">
        <span className="pill clock">
          <span className="dot" style={{ background: 'var(--text-faint)' }} />
          {clock.toLocaleTimeString('en-IN', { hour12: false })} IST
        </span>
        {/* <span className={`pill ${chainOk ? 'ok' : 'bad'}`}>
          <span className="dot" />
          {chainOk ? `CHAIN VALID · H${chainInfo.height}` : 'CHAIN BROKEN'}
        </span> */}
      </div>
    </header>
  );
}
