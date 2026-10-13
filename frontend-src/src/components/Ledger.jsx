import React, { useEffect, useRef, useState } from 'react';
import { fmtINR } from '../api.js';

function blockDetail(tx) {
  if (!tx) return '';
  switch (tx.type) {
    case 'GENESIS':
      return `Treasury seeded ${fmtINR(tx.treasury)}`;
    case 'DEPOSIT':
      return (
        <>
          +{fmtINR(tx.amount)}
          <br />
          Bal <b>{fmtINR(tx.treasury_after)}</b>
        </>
      );
    case 'DISBURSE':
      return (
        <>
          {tx.region || ''}
          <br />
          {fmtINR(tx.amount)} &middot; {tx.risk_category || ''}
        </>
      );
    case 'ASSESS':
      return (
        <>
          {tx.region || ''}
          <br />
          score {tx.risk_score ?? '—'} &middot; {tx.risk_category || ''}
        </>
      );
    default:
      return '';
  }
}

export default function Ledger({ blocks, chainInfo, onVerify, onDeposit }) {
  const scrollRef = useRef(null);
  const [amount, setAmount] = useState('');
  const [verifying, setVerifying] = useState(false);
  const [depositing, setDepositing] = useState(false);

  const ordered = [...blocks].reverse(); // oldest -> newest, left to right

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollLeft = el.scrollWidth;
  }, [blocks.length]);

  async function handleVerify() {
    setVerifying(true);
    try {
      await onVerify();
    } finally {
      setVerifying(false);
    }
  }

  async function handleDeposit() {
    const value = parseFloat(amount);
    if (!value || value <= 0) return;
    setDepositing(true);
    try {
      await onDeposit(value);
      setAmount('');
    } finally {
      setDepositing(false);
    }
  }

  return (
    <section className="panel" style={{ marginBottom: 16 }}>
      <div className="panel-head">
        <h2>
          <span className="n">03</span> Hash-Chain Ledger
        </h2>
        {/* <button className="btn-ghost" onClick={handleVerify} type="button" disabled={verifying}>
          {verifying ? 'Verifying…' : 'Verify Chain'}
        </button> */}
      </div>
      <div className="panel-body">
        <div className="chain-scroll" ref={scrollRef}>
          {ordered.map((b, i) => (
            <React.Fragment key={b.hash}>
              {i > 0 && <div className="connector">&rarr;</div>}
              <div className={`block type-${b.tx?.type || 'GENESIS'}`}>
                <div className="b-idx">#{b.index}</div>
                <div className="b-type">{b.tx?.type || 'BLOCK'}</div>
                <div className="b-detail">
                  {blockDetail(b.tx)}

                  {b.tx?.ethereum_tx_hash && (
                    <>
                      <br />
                      <a
                        href={b.tx.explorer_url}
                        target="_blank"
                        rel="noreferrer"
                        title={b.tx.ethereum_tx_hash}
                      >
                        View transaction on Sepolia Etherscan
                      </a>
                      <br />
                      Block: {b.tx.ethereum_block_number}
                    </>
                  )}
                </div>
                <div className="b-hash" title={b.hash}>
                  {b.hash.slice(0, 10)}&hellip;{b.hash.slice(-6)}
                </div>
              </div>
            </React.Fragment>
          ))}
        </div>
        <div className="deposit-row">
          <input
            type="number"
            placeholder="Deposit amount (₹)"
            min="1"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
          />
          <button className="btn-ghost" style={{ width: 'auto', padding: '9px 16px' }} onClick={handleDeposit} disabled={depositing} type="button">
            {depositing ? 'Depositing…' : 'Deposit to treasury'}
          </button>
        </div>
      </div>
    </section>
  );
}
