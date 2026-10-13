"""Ethereum Sepolia integration for the ReliefFund smart contract."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from eth_account import Account
from web3 import Web3


ROOT = Path(__file__).resolve().parent
ABI_PATH = ROOT / "contract_abi.json"
SEPOLIA_CHAIN_ID = 11155111


class EthereumAdapter:
    """Connects the FastAPI risk oracle to ReliefFund on Ethereum Sepolia."""

    def __init__(self) -> None:
        load_dotenv(ROOT / ".env")

        self.enabled = os.getenv("ETHEREUM_ENABLED", "false").lower() == "true"
        self.w3: Web3 | None = None
        self.contract = None
        self.account = None
        self.contract_address: str | None = None

        # Lets the app run in local-demo mode until Ethereum is configured.
        if not self.enabled:
            return

        rpc_url = os.getenv("SEPOLIA_RPC_URL")
        contract_address = os.getenv("RELIEF_CONTRACT_ADDRESS")
        private_key = os.getenv("ORACLE_PRIVATE_KEY")

        missing = [
            name
            for name, value in {
                "SEPOLIA_RPC_URL": rpc_url,
                "RELIEF_CONTRACT_ADDRESS": contract_address,
                "ORACLE_PRIVATE_KEY": private_key,
            }.items()
            if not value
        ]
        if missing:
            raise RuntimeError(
                "Ethereum is enabled but these .env values are missing: "
                + ", ".join(missing)
            )

        if not ABI_PATH.exists():
            raise RuntimeError(
                "contract_abi.json is missing. Copy the ABI from Remix into this file."
            )

        self.w3 = Web3(
            Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 30})
        )

        if not self.w3.is_connected():
            raise RuntimeError(
                "Could not connect to Sepolia. Check SEPOLIA_RPC_URL in .env."
            )

        if self.w3.eth.chain_id != SEPOLIA_CHAIN_ID:
            raise RuntimeError(
                f"RPC is connected to chain {self.w3.eth.chain_id}, not Sepolia "
                f"({SEPOLIA_CHAIN_ID})."
            )

        self.contract_address = Web3.to_checksum_address(contract_address)
        abi = json.loads(ABI_PATH.read_text(encoding="utf-8"))

        self.contract = self.w3.eth.contract(
            address=self.contract_address,
            abi=abi,
        )

        self.account = Account.from_key(private_key)

        configured_oracle = Web3.to_checksum_address(
            self.contract.functions.oracle().call()
        )
        if configured_oracle != self.account.address:
            raise RuntimeError(
                "The wallet in ORACLE_PRIVATE_KEY is not the oracle configured "
                "in the deployed contract."
            )

    def status(self) -> dict[str, Any]:
        """Small status object safe to return to the dashboard."""
        if not self.enabled:
            return {
                "enabled": False,
                "network": "local demo",
                "message": "Ethereum integration is disabled",
            }

        return {
            "enabled": True,
            "network": "Ethereum Sepolia",
            "chain_id": SEPOLIA_CHAIN_ID,
            "contract_address": self.contract_address,
            "oracle_address": self.account.address,
            "connected": self.w3.is_connected(),
        }

    def snapshot(self) -> dict[str, Any]:
        """Reads current treasury values directly from the deployed contract."""
        if not self.enabled:
            raise RuntimeError("Ethereum integration is disabled")

        return {
            "treasury": int(self.contract.functions.treasury().call()),
            "total_disbursed": int(
                self.contract.functions.totalDisbursed().call()
            ),
            "payout_count": int(self.contract.functions.payoutCount().call()),
            "high_threshold": int(
                self.contract.functions.HIGH_THRESHOLD().call()
            ),
            "severe_threshold": int(
                self.contract.functions.SEVERE_THRESHOLD().call()
            ),
            "contract": "ReliefFund.sol",
            "address": self.contract_address,
            "oracle": self.account.address,
            "network": "Ethereum Sepolia",
            "on_chain": True,
        }

    @staticmethod
    def assessment_id_to_bytes32(assessment_id: str) -> bytes:
        """Produces the bytes32 value expected by Solidity."""
        return Web3.keccak(text=assessment_id)

    def _send_transaction(self, function_call) -> dict[str, Any]:
        """Signs, sends, and waits for one Sepolia transaction."""
        nonce = self.w3.eth.get_transaction_count(
            self.account.address,
            "pending",
        )

        tx_params: dict[str, Any] = {
            "from": self.account.address,
            "nonce": nonce,
            "chainId": SEPOLIA_CHAIN_ID,
        }

        # Uses current EIP-1559 gas settings when the RPC supports them.
        latest_block = self.w3.eth.get_block("latest")
        base_fee = latest_block.get("baseFeePerGas")

        if base_fee is not None:
            priority_fee = self.w3.to_wei(1, "gwei")
            tx_params["maxPriorityFeePerGas"] = priority_fee
            tx_params["maxFeePerGas"] = int(base_fee * 2 + priority_fee)
        else:
            tx_params["gasPrice"] = self.w3.eth.gas_price

        unsigned_tx = function_call.build_transaction(tx_params)
        signed_tx = self.account.sign_transaction(unsigned_tx)

        tx_hash_bytes = self.w3.eth.send_raw_transaction(
            signed_tx.raw_transaction
        )
        receipt = self.w3.eth.wait_for_transaction_receipt(
            tx_hash_bytes,
            timeout=180,
        )

        tx_hash = self.w3.to_hex(tx_hash_bytes)

        if receipt["status"] != 1:
            raise RuntimeError(f"Ethereum transaction failed: {tx_hash}")

        return {
            "tx_hash": tx_hash,
            "block_number": int(receipt["blockNumber"]),
            "receipt_status": "confirmed",
            "explorer_url": f"https://sepolia.etherscan.io/tx/{tx_hash}",
        }

    def execute_disbursal(
        self,
        assessment_id: str,
        region: str,
        hazard: str,
        risk_score: float,
        category: str,
    ) -> dict[str, Any]:
        """Writes an eligible payout to the Sepolia smart contract."""
        if not self.enabled:
            raise RuntimeError("Ethereum integration is disabled")

        assessment_key = self.assessment_id_to_bytes32(assessment_id)
        risk_score_x10 = int(round(float(risk_score) * 10))
        category = str(category).upper()
        hazard = str(hazard).lower()

        if self.contract.functions.spent(assessment_key).call():
            return {
                "status": "rejected",
                "reason": "assessment already disbursed",
                "amount": 0,
                "on_chain": False,
            }

        # Call is free: it predicts the Solidity payout before sending anything.
        amount = int(
            self.contract.functions.allocateAmount(
                risk_score_x10,
                category,
                hazard,
            ).call()
        )

        if amount <= 0:
            return {
                "status": "rejected",
                "reason": "risk below HIGH threshold — no automatic disbursal",
                "amount": 0,
                "on_chain": False,
            }

        tx_data = self._send_transaction(
            self.contract.functions.executeDisbursal(
                assessment_key,
                region,
                hazard,
                risk_score_x10,
                category,
            )
        )

        return {
            "status": "executed",
            "reason": "smart contract threshold met on Ethereum Sepolia",
            "amount": amount,
            "assessment_id": assessment_id,
            "region": region,
            "hazard": hazard,
            "on_chain": True,
            **tx_data,
        }

    def deposit(self, amount: float) -> dict[str, Any]:
        """Adds whole-number relief credits to the on-chain treasury."""
        if not self.enabled:
            raise RuntimeError("Ethereum integration is disabled")

        if not float(amount).is_integer():
            raise ValueError(
                "Ethereum treasury deposits must be whole-number relief credits."
            )

        amount_int = int(amount)

        if amount_int <= 0:
            raise ValueError("Deposit must be greater than zero.")

        owner = Web3.to_checksum_address(self.contract.functions.owner().call())
        if owner != self.account.address:
            raise RuntimeError(
                "The oracle wallet is not the contract owner, so it cannot deposit."
            )

        tx_data = self._send_transaction(
            self.contract.functions.deposit(amount_int)
        )

        return {
            "amount": amount_int,
            "on_chain": True,
            **tx_data,
        }