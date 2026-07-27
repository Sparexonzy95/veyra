const hre = require("hardhat");

async function main() {
  const escrowAddress = process.env.VEYRA_ESCROW_ADDRESS;
  if (!escrowAddress) throw new Error("VEYRA_ESCROW_ADDRESS is required");
  const escrow = await hre.ethers.getContractAt("VeyraJobEscrow", escrowAddress);
  const [signer] = await hre.ethers.getSigners();
  const pendingOwner = await escrow.pendingOwner();
  if (pendingOwner.toLowerCase() !== signer.address.toLowerCase()) {
    throw new Error(`Signer ${signer.address} is not pending owner ${pendingOwner}`);
  }
  await (await escrow.acceptOwnership()).wait();
  console.log("Ownership accepted by:", signer.address);
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
