import React, { useCallback, useEffect, useState } from 'react';
import { api } from './api.js';
import Header from './components/Header.jsx';
import StatStrip from './components/StatStrip.jsx';
import AssessmentPanel from './components/AssessmentPanel.jsx';
import Ledger from './components/Ledger.jsx';
import NowcastPanel from './components/NowcastPanel.jsx';

export default function App() {
  const [engineMode, setEngineMode] = useState('');
  const [treasury, setTreasury] = useState(null);
  const [chainInfo, setChainInfo] = useState(null);
  const [ledgerBlocks, setLedgerBlocks] = useState([]);

  const pullSnapshot = useCallback(async () => {
    try {
      const data = await api.getState();
      setEngineMode(data.engine_mode);
      setTreasury(data.treasury);
      setChainInfo(data.chain);
      setLedgerBlocks(data.ledger || []);
    } catch (err) {
      console.error('Failed to load state', err);
    }
  }, []);

  const refreshLedger = useCallback(async () => {
    try {
      const data = await api.getState();
      setTreasury(data.treasury);
      setChainInfo(data.chain);
      setLedgerBlocks(data.ledger || []);
    } catch (err) {
      console.error('Failed to refresh ledger', err);
    }
  }, []);

  useEffect(() => {
    pullSnapshot();
  }, [pullSnapshot]);

  const handleAssessed = useCallback(
    (data) => {
      setTreasury(data.allocation.treasury);
      setChainInfo(data.allocation.chain);
      refreshLedger();
    },
    [refreshLedger]
  );

  const handleVerify = useCallback(async () => {
    const data = await api.verify();
    setChainInfo(data);
  }, []);

  const handleDeposit = useCallback(async (amount) => {
    await api.deposit(amount);
    await refreshLedger();
  }, [refreshLedger]);

  return (
    <div className="wrap">
      <Header engineMode={engineMode} chainInfo={chainInfo} />
      <StatStrip treasury={treasury} />

      <section className="main-grid">
        <AssessmentPanel onAssessed={handleAssessed} />
      </section>

      <NowcastPanel />
      <Ledger blocks={ledgerBlocks} chainInfo={chainInfo} onVerify={handleVerify} onDeposit={handleDeposit} />

      <div className="footer-note">
        National Disaster Relief Command &middot; every disbursal is written to the SHA-256 ledger above and cannot be quietly edited
      </div>
    </div>
  );
}
