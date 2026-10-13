"""Tamper-evident hash-chain ledger for relief-fund transactions."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any


LEDGER_PATH = Path(__file__).resolve().parent / "ledger" / "chain.json"


def _sha(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ReliefChain:
    def __init__(self, path: Path = LEDGER_PATH):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.blocks: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self.blocks = data.get("blocks", [])
            except json.JSONDecodeError:
                self.blocks = []
        if not self.blocks:
            genesis = self._make_block(
                index=0,
                prev="0" * 64,
                tx={
                    "type": "GENESIS",
                    "note": "National Disaster Relief Treasury initialized",
                    "treasury": 50_000_000,
                },
            )
            self.blocks = [genesis]
            self._persist()

    def _persist(self) -> None:
        self.path.write_text(
            json.dumps({"blocks": self.blocks}, indent=2),
            encoding="utf-8",
        )

    def _make_block(self, index: int, prev: str, tx: dict[str, Any]) -> dict[str, Any]:
        body = {
            "index": index,
            "timestamp": time.time(),
            "prev_hash": prev,
            "tx": tx,
        }
        body["hash"] = _sha(json.dumps(body, sort_keys=True, default=str))
        return body

    def append(self, tx: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            prev = self.blocks[-1]["hash"]
            block = self._make_block(len(self.blocks), prev, tx)
            self.blocks.append(block)
            self._persist()
            return block

    def verify(self) -> dict[str, Any]:
        with self._lock:
            for i, block in enumerate(self.blocks):
                copy = {k: v for k, v in block.items() if k != "hash"}
                expected = _sha(json.dumps(copy, sort_keys=True, default=str))
                if expected != block["hash"]:
                    return {"valid": False, "broken_at": i, "reason": "hash mismatch"}
                if i > 0 and block["prev_hash"] != self.blocks[i - 1]["hash"]:
                    return {"valid": False, "broken_at": i, "reason": "broken chain link"}
            return {
                "valid": True,
                "height": len(self.blocks),
                "tip": self.blocks[-1]["hash"],
            }

    def recent(self, n: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            return list(reversed(self.blocks[-n:]))
