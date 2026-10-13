"""Python execution of ReliefFund.sol rules (local chain / demo oracle)."""

from __future__ import annotations

from dataclasses import dataclass, field


HAZARD_MULTIPLIER_BPS = {
    "flood": 12000,
    "cyclone": 11500,
    "earthquake": 13000,
    "multi": 12500,
}


@dataclass
class ReliefFundContract:
    high_threshold: int = 50
    severe_threshold: int = 75
    treasury: float = 50_000_000.0
    total_disbursed: float = 0.0
    payout_count: int = 0
    spent: set[str] = field(default_factory=set)

    def allocate_amount(self, risk_score: float, category: str, hazard: str) -> float:
        cat = (category or "").upper().replace("VERY_LOW", "LOW")
        if cat in {"LOW", "MODERATE", "VERY_LOW", "INSUFFICIENT_DATA", "ERROR"} and risk_score < self.high_threshold:
            return 0.0
        bps = HAZARD_MULTIPLIER_BPS.get(hazard.lower(), 10000)
        if cat == "SEVERE" or risk_score >= self.severe_threshold:
            share = 0.18
        elif cat == "HIGH" or risk_score >= self.high_threshold:
            share = 0.08
        else:
            return 0.0
        raw = self.treasury * share * (risk_score / 100.0) * (bps / 10000.0)
        floor, cap = 75_000.0, min(4_000_000.0, self.treasury * 0.25)
        amount = max(floor, min(cap, raw))
        return round(min(amount, self.treasury), 2)

    def execute_disbursal(
        self,
        assessment_id: str,
        region: str,
        hazard: str,
        risk_score: float,
        category: str,
    ) -> dict:
        if assessment_id in self.spent:
            return {"status": "rejected", "reason": "assessment already disbursed", "amount": 0}
        amount = self.allocate_amount(risk_score, category, hazard)
        if amount <= 0:
            return {
                "status": "rejected",
                "reason": "risk below HIGH threshold — no automatic disbursal",
                "amount": 0,
            }
        if amount > self.treasury:
            return {"status": "rejected", "reason": "treasury insufficient", "amount": 0}

        self.spent.add(assessment_id)
        self.treasury = round(self.treasury - amount, 2)
        self.total_disbursed = round(self.total_disbursed + amount, 2)
        self.payout_count += 1
        return {
            "status": "executed",
            "reason": "smart contract threshold met",
            "amount": amount,
            "treasury_after": self.treasury,
            "payout_count": self.payout_count,
            "region": region,
            "hazard": hazard,
        }

    def deposit(self, amount: float) -> dict:
        self.treasury = round(self.treasury + amount, 2)
        return {"treasury": self.treasury, "deposited": amount}

    def snapshot(self) -> dict:
        return {
            "treasury": self.treasury,
            "total_disbursed": self.total_disbursed,
            "payout_count": self.payout_count,
            "high_threshold": self.high_threshold,
            "severe_threshold": self.severe_threshold,
            "contract": "ReliefFund.sol",
            "oracle": "0xRISK-ORACLE-NDMA",
            "address": "0xRELIEF-FUND-TREASURY",
        }
