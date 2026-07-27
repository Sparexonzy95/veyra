const hre = require("hardhat");

async function main() {
  const escrowAddress = process.env.VEYRA_ESCROW_ADDRESS;
  const agentAddress = process.env.VEYRA_AGENT_ADDRESS;
  if (!escrowAddress || !agentAddress) throw new Error("VEYRA_ESCROW_ADDRESS and VEYRA_AGENT_ADDRESS are required");
  const escrow = await hre.ethers.getContractAt("VeyraJobEscrow", escrowAddress);
  await (await escrow.setAgentAuthorised(agentAddress, true)).wait();
  console.log("Authorised agent:", agentAddress);
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
