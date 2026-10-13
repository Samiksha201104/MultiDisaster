// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

/**
 * @title ReliefFund
 * @dev Smart contract for National Disaster Relief Fund management
 */
contract ReliefFund {
    address public owner;
    uint256 public totalFunds;
    uint256 public totalDisbursed;
    
    struct Disbursal {
        uint256 id;
        string region;
        string hazard;
        uint256 amount;
        uint256 timestamp;
        bool executed;
    }
    
    mapping(uint256 => Disbursal) public disbursals;
    uint256 public disburalCount = 0;
    
    event DisbursalExecuted(uint256 id, string region, uint256 amount);
    event FundsDeposited(uint256 amount);
    
    constructor() {
        owner = msg.sender;
        totalFunds = 0;
        totalDisbursed = 0;
    }
    
    modifier onlyOwner() {
        require(msg.sender == owner, "Only owner can call this");
        _;
    }
    
    function deposit() public payable {
        require(msg.value > 0, "Deposit amount must be greater than 0");
        totalFunds += msg.value;
        emit FundsDeposited(msg.value);
    }
    
    function disburse(string memory region, string memory hazard, uint256 amount) public onlyOwner returns (uint256) {
        require(amount > 0, "Amount must be greater than 0");
        require(totalFunds >= amount, "Insufficient funds");
        
        disburalCount++;
        disbursals[disburalCount] = Disbursal({
            id: disburalCount,
            region: region,
            hazard: hazard,
            amount: amount,
            timestamp: block.timestamp,
            executed: true
        });
        
        totalFunds -= amount;
        totalDisbursed += amount;
        
        emit DisbursalExecuted(disburalCount, region, amount);
        return disburalCount;
    }
    
    function getBalance() public view returns (uint256) {
        return totalFunds;
    }
    
    function getTotalDisbursed() public view returns (uint256) {
        return totalDisbursed;
    }
    
    function getDisbursalDetails(uint256 id) public view returns (
        string memory region,
        string memory hazard,
        uint256 amount,
        uint256 timestamp
    ) {
        Disbursal memory d = disbursals[id];
        return (d.region, d.hazard, d.amount, d.timestamp);
    }
    
    receive() external payable {
        deposit();
    }
}
