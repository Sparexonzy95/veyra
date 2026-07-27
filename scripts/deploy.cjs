const hre = require("hardhat");
const fs = require("node:fs");
const path = require("node:path");

function required(name) {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is required`);
  return value;
}

async function assertContract(address, label) {
  const code = await hre.ethers.provider.getCode(address);
  if (code === "0x") throw new Error(`${label} has no contract code: ${address}`);
}

async function main() {
  const network = await hre.ethers.provider.getNetwork();
  if (network.chainId !== 5042002n) {
    throw new Error(`Refusing to deploy on chain ${network.chainId}; expected Arc Testnet 5042002`);
  }

  const [deployer] = await hre.ethers.getSigners();
  const tokenAddress = required("ARC_USDC_ADDRESS");
  const agentAddress = required("VEYRA_AGENT_ADDRESS");
  const verifierAddress = required("VEYRA_VERIFIER_ADDRESS");
  const desiredOwner = process.env.VEYRA_OWNER_ADDRESS || deployer.address;
  const graceSeconds = BigInt(process.env.VEYRA_VERIFICATION_GRACE_SECONDS || "86400");
  const claimSubmissionSeconds = BigInt(process.env.VEYRA_CLAIM_SUBMISSION_SECONDS || "43200");
  const minimumKarmaUsdc = process.env.VEYRA_MIN_KARMA_USDC || "1";

  const expectedArcUsdc = "0x3600000000000000000000000000000000000000";
  if (tokenAddress.toLowerCase() !== expectedArcUsdc.toLowerCase()) {
    throw new Error(`ARC_USDC_ADDRESS must be the official Arc Testnet USDC address ${expectedArcUsdc}`);
  }
  if (agentAddress.toLowerCase() === verifierAddress.toLowerCase()) {
    throw new Error("VEYRA_AGENT_ADDRESS and VEYRA_VERIFIER_ADDRESS must be different wallets");
  }

  for (const [value, label] of [
    [tokenAddress, "ARC_USDC_ADDRESS"],
    [agentAddress, "VEYRA_AGENT_ADDRESS"],
    [verifierAddress, "VEYRA_VERIFIER_ADDRESS"],
    [desiredOwner, "VEYRA_OWNER_ADDRESS"]
  ]) {
    if (!hre.ethers.isAddress(value) || value === hre.ethers.ZeroAddress) {
      throw new Error(`${label} must be a non-zero EVM address`);
    }
  }

  await assertContract(tokenAddress, "Payment token");
  const token = new hre.ethers.Contract(
    tokenAddress,
    ["function decimals() view returns (uint8)", "function symbol() view returns (string)"],
    deployer
  );
  const decimals = await token.decimals();
  const symbol = await token.symbol().catch(() => "USDC");
  const minimumKarmaBudget = hre.ethers.parseUnits(minimumKarmaUsdc, decimals);

  console.log("Network: Arc Testnet (5042002)");
  console.log("Deployer:", deployer.address);
  console.log("Payment token:", tokenAddress, symbol, `decimals=${decimals}`);
  console.log("Verification grace:", graceSeconds.toString(), "seconds");
  console.log("Claim-to-submission period:", claimSubmissionSeconds.toString(), "seconds");
  console.log("Minimum Karma budget:", minimumKarmaBudget.toString(), "base units");

  const Factory = await hre.ethers.getContractFactory("VeyraJobEscrow");
  const escrow = await Factory.deploy(
    tokenAddress,
    deployer.address,
    minimumKarmaBudget,
    graceSeconds,
    claimSubmissionSeconds
  );
  await escrow.waitForDeployment();

  const escrowAddress = await escrow.getAddress();
  const deploymentTx = escrow.deploymentTransaction();

  await (await escrow.setAgentAuthorised(agentAddress, true)).wait();
  await (await escrow.setVerifierAuthorised(verifierAddress, true)).wait();

  let ownershipTransferStarted = false;
  if (desiredOwner.toLowerCase() !== deployer.address.toLowerCase()) {
    await (await escrow.transferOwnership(desiredOwner)).wait();
    ownershipTransferStarted = true;
  }

  const deployment = {
    network: "arcTestnet",
    chainId: Number(network.chainId),
    contract: "VeyraJobEscrow",
    contractAddress: escrowAddress,
    deploymentTransactionHash: deploymentTx?.hash || null,
    deployer: deployer.address,
    paymentToken: tokenAddress,
    paymentTokenSymbol: symbol,
    paymentTokenDecimals: Number(decimals),
    initialOwner: deployer.address,
    desiredOwner,
    ownershipTransferStarted,
    authorisedAgent: agentAddress,
    authorisedVerifier: verifierAddress,
    minimumKarmaBudget: minimumKarmaBudget.toString(),
    verificationGracePeriod: graceSeconds.toString(),
    claimSubmissionPeriod: claimSubmissionSeconds.toString(),
    deployedAt: new Date().toISOString()
  };

  fs.mkdirSync(path.join(process.cwd(), "deployments"), { recursive: true });
  const outputPath = path.join(process.cwd(), "deployments", "arc-testnet.json");
  fs.writeFileSync(outputPath, JSON.stringify(deployment, null, 2) + "\n");

  console.log("\nVeyraJobEscrow:", escrowAddress);
  console.log("Transaction:", deployment.deploymentTransactionHash);
  console.log("Deployment record:", outputPath);
  if (ownershipTransferStarted) {
    console.log("Ownership is pending. The desired owner must run npm run accept:ownership.");
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
