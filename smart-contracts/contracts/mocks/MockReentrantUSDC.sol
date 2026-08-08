// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20Metadata} from "../interfaces/IERC20Metadata.sol";

/// @dev Test-only token that attempts a callback during transfers.
contract MockReentrantUSDC is IERC20Metadata {
    string public constant name = "Reentrant Mock USDC";
    string public constant symbol = "rUSDC";
    uint8 public constant decimals = 6;

    uint256 public totalSupply;
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    address public attackTarget;
    bytes public attackData;
    bool public attackEnabled;
    bool public reentrySucceeded;
    bool private attacking;

    event Transfer(address indexed from, address indexed to, uint256 amount);
    event Approval(address indexed owner, address indexed spender, uint256 amount);

    function configureAttack(address target, bytes calldata data, bool enabled) external {
        attackTarget = target;
        attackData = data;
        attackEnabled = enabled;
        reentrySucceeded = false;
    }

    function mint(address to, uint256 amount) external {
        balanceOf[to] += amount;
        totalSupply += amount;
        emit Transfer(address(0), to, amount);
    }

    function approve(address spender, uint256 amount) external returns (bool) {
        allowance[msg.sender][spender] = amount;
        emit Approval(msg.sender, spender, amount);
        return true;
    }

    function transfer(address to, uint256 amount) external returns (bool) {
        _attemptReentry();
        _transfer(msg.sender, to, amount);
        return true;
    }

    function transferFrom(address from, address to, uint256 amount) external returns (bool) {
        uint256 currentAllowance = allowance[from][msg.sender];
        require(currentAllowance >= amount, "insufficient allowance");
        allowance[from][msg.sender] = currentAllowance - amount;
        _attemptReentry();
        _transfer(from, to, amount);
        return true;
    }

    function _attemptReentry() private {
        if (!attackEnabled || attacking || attackTarget == address(0)) return;
        attacking = true;
        (reentrySucceeded,) = attackTarget.call(attackData);
        attacking = false;
    }

    function _transfer(address from, address to, uint256 amount) private {
        require(balanceOf[from] >= amount, "insufficient balance");
        balanceOf[from] -= amount;
        balanceOf[to] += amount;
        emit Transfer(from, to, amount);
    }
}
