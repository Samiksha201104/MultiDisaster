// Thin wrapper around the FastAPI backend. Every route here already exists in
// app.py and is left completely untouched — this file just calls it.

async function asJson(res) {
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch (_) {
      /* ignore parse errors */
    }
    throw new Error(detail);
  }
  return res.json();
}

export const api = {
  getState: () => fetch('/api/state').then(asJson),
  getContract: () => fetch('/api/contract').then(asJson),
  verify: () => fetch('/api/verify').then(asJson),
  assess: (body) =>
    fetch('/api/assess', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(asJson),
  deposit: (amount) =>
    fetch('/api/deposit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ amount }),
    }).then(asJson),
  nowcast: (body) =>
    fetch('/api/nowcast', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(asJson),
};

export function fmtINR(n) {
  return '₹' + Number(n || 0).toLocaleString('en-IN', { maximumFractionDigits: 0 });
}

export function fmtTime(ts) {
  return new Date((ts || Date.now() / 1000) * 1000).toLocaleTimeString('en-IN', { hour12: false });
}

export function catColorVar(cat) {
  const c = String(cat || '').toUpperCase();
  if (c === 'SEVERE') return 'var(--red)';
  if (c === 'HIGH') return 'var(--amber)';
  if (c === 'MODERATE') return 'var(--yellow)';
  if (c === 'LOW' || c === 'VERY_LOW') return 'var(--green)';
  return 'var(--text-faint)';
}

export function catClass(cat) {
  return 'cat-' + String(cat || 'LOW').toUpperCase().replace(/\s+/g, '_');
}