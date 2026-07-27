const hre = require("hardhat");

async function main() {
  const escrowAddress = process.env.VEYRA_ESCROW_ADDRESS;
  const verifierAddress = process.env.VEYRA_VERIFIER_ADDRESS;
  if (!escrowAddress || !verifierAddress) throw new Error("VEYRA_ESCROW_ADDRESS and VEYRA_VERIFIER_ADDRESS are required");
  const escrow = await hre.ethers.getContractAt("VeyraJobEscrow", escrowAddress);
  await (await escrow.setVerifierAuthorised(verifierAddress, true)).wait();
  console.log("Authorised verifier:", verifierAddress);
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
