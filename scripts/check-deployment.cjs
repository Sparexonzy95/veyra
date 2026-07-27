const hre = require("hardhat");

function required(name) {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is required`);
  return value;
}

async function main() {
  const network = await hre.ethers.provider.getNetwork();
  if (network.chainId !== 5042002n) {
    throw new Error(`Expected Arc Testnet 5042002, got ${network.chainId}`);
  }

  const address = required("VEYRA_ESCROW_ADDRESS");
  const code = await hre.ethers.provider.getCode(address);
  if (code === "0x") throw new Error(`No contract code at ${address}`);

  const escrow = await hre.ethers.getContractAt("VeyraJobEscrow", address);
  const agent = process.env.VEYRA_AGENT_ADDRESS;
  const verifier = process.env.VEYRA_VERIFIER_ADDRESS;

  console.log("VeyraJobEscrow:", address);
  console.log("Owner:", await escrow.owner());
  console.log("Pending owner:", await escrow.pendingOwner());
  console.log("Payment token:", await escrow.paymentToken());
  console.log("Paused:", await escrow.paused());
  console.log("Job count:", (await escrow.jobCount()).toString());
  console.log("Total escrowed:", (await escrow.totalEscrowed()).toString());
  console.log("Minimum Karma budget:", (await escrow.minimumKarmaBudget()).toString());
  console.log("Verification grace:", (await escrow.verificationGracePeriod()).toString());
  console.log("Claim-to-submission period:", (await escrow.claimSubmissionPeriod()).toString());
  console.log("Escrow solvent:", await escrow.isSolvent());
  if (agent) console.log("Agent authorised:", await escrow.authorisedAgents(agent));
  if (verifier) console.log("Verifier authorised:", await escrow.authorisedVerifiers(verifier));
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
