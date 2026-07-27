// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "../interfaces/IERC20.sol";

library SafeERC20 {
    error SafeERC20FailedOperation(address token);

    function safeTransfer(IERC20 token, address to, uint256 amount) internal {
        _callOptionalReturn(token, abi.encodeCall(token.transfer, (to, amount)));
    }

    function safeTransferFrom(IERC20 token, address from, address to, uint256 amount) internal {
        _callOptionalReturn(token, abi.encodeCall(token.transferFrom, (from, to, amount)));
    }

    function _callOptionalReturn(IERC20 token, bytes memory data) private {
        address tokenAddress = address(token);
        if (tokenAddress.code.length == 0) revert SafeERC20FailedOperation(tokenAddress);
        (bool success, bytes memory returndata) = tokenAddress.call(data);
        if (!success || (returndata.length != 0 && !abi.decode(returndata, (bool)))) {
            revert SafeERC20FailedOperation(address(token));
        }
    }
}
