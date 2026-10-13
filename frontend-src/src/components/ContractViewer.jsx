import React from 'react';

export default function ContractViewer({ contract }) {
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>
          <span className="n">05</span> Smart Contract &mdash; ReliefFund.sol
        </h2>
      </div>
      <div className="panel-body">
        <div className="contract-meta">
          <div className="m">
            <div className="k">Contract address</div>
            <div className="v">{contract?.address || '—'}</div>
          </div>
          <div className="m">
            <div className="k">Risk oracle</div>
            <div className="v">{contract?.oracle || '—'}</div>
          </div>
        </div>
        <pre className="code">{contract?.solidity || 'Loading source…'}</pre>
      </div>
    </section>
  );
}
