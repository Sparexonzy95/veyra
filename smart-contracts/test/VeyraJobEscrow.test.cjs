const { expect } = require("chai");
const { ethers, network } = require("hardhat");

const USDC = (value) => ethers.parseUnits(String(value), 6);
const HASH = (label) => ethers.keccak256(ethers.toUtf8Bytes(label));
const ZERO_HASH = ethers.ZeroHash;

async function latestTimestamp() {
  const block = await ethers.provider.getBlock("latest");
  return Number(block.timestamp);
}

async function increaseTime(seconds) {
  await network.provider.send("evm_increaseTime", [seconds]);
  await network.provider.send("evm_mine");
}

describe("VeyraJobEscrow", function () {
  let owner, pendingOwner, client, agent, agent2, verifier, verifier2, outsider;
  let token, escrow;
  const grace = 24 * 60 * 60;
  const claimPeriod = 12 * 60 * 60;

  beforeEach(async function () {
    [owner, pendingOwner, client, agent, agent2, verifier, verifier2, outsider] = await ethers.getSigners();

    const Token = await ethers.getContractFactory("MockUSDC");
    token = await Token.deploy();
    await token.waitForDeployment();

    const Escrow = await ethers.getContractFactory("VeyraJobEscrow");
    escrow = await Escrow.deploy(await token.getAddress(), owner.address, USDC(1), grace, claimPeriod);
    await escrow.waitForDeployment();

    await token.mint(client.address, USDC(10_000));
    await token.connect(client).approve(await escrow.getAddress(), ethers.MaxUint256);

    await escrow.connect(owner).setAgentAuthorised(agent.address, true);
    await escrow.connect(owner).setAgentAuthorised(agent2.address, true);
    await escrow.connect(owner).setVerifierAuthorised(verifier.address, true);
    await escrow.connect(owner).setVerifierAuthorised(verifier2.address, true);
  });

  async function createJob({
    invitedProvider = ethers.ZeroAddress,
    verifierAddress = verifier.address,
    budget = USDC(50),
    duration = 2 * 24 * 60 * 60,
    repositoryHash = HASH("repo"),
    taskHash = HASH("task"),
    policyHash = HASH("policy")
  } = {}) {
    const expiresAt = (await latestTimestamp()) + duration;
    const tx = await escrow.connect(client).createJob(
      invitedProvider,
      verifierAddress,
      budget,
      expiresAt,
      repositoryHash,
      taskHash,
      policyHash
    );
    await tx.wait();
    return { jobId: await escrow.jobCount(), expiresAt, budget, repositoryHash, taskHash, policyHash };
  }

  async function claimAndSubmit(jobId, worker = agent, commitLabel = "commit-1", pr = 17) {
    await escrow.connect(worker).claimJob(jobId);
    const commitHash = HASH(commitLabel);
    await escrow.connect(worker).submitWork(jobId, commitHash, pr);
    const deliverableHash = await escrow.computeDeliverableHash(jobId, commitHash, pr);
    return { commitHash, deliverableHash, pr };
  }

  describe("deployment and administration", function () {
    it("rejects a token address without contract code", async function () {
      const Escrow = await ethers.getContractFactory("VeyraJobEscrow");
      await expect(Escrow.deploy(outsider.address, owner.address, USDC(1), grace, claimPeriod))
        .to.be.revertedWithCustomError(Escrow, "NotContract");
    });

    it("rejects an unsafe verification grace-period configuration", async function () {
      const Escrow = await ethers.getContractFactory("VeyraJobEscrow");
      await expect(Escrow.deploy(await token.getAddress(), owner.address, USDC(1), 60, claimPeriod))
        .to.be.revertedWithCustomError(Escrow, "InvalidVerificationGracePeriod");
      await expect(Escrow.deploy(await token.getAddress(), owner.address, USDC(1), 8 * 24 * 60 * 60, claimPeriod))
        .to.be.revertedWithCustomError(Escrow, "InvalidVerificationGracePeriod");
    });

    it("rejects an unsafe claim-to-submission period", async function () {
      const Escrow = await ethers.getContractFactory("VeyraJobEscrow");
      await expect(Escrow.deploy(await token.getAddress(), owner.address, USDC(1), grace, 60))
        .to.be.revertedWithCustomError(Escrow, "InvalidClaimSubmissionPeriod");
      await expect(Escrow.deploy(await token.getAddress(), owner.address, USDC(1), grace, 31 * 24 * 60 * 60))
        .to.be.revertedWithCustomError(Escrow, "InvalidClaimSubmissionPeriod");
    });

    it("uses two-step ownership transfer", async function () {
      await escrow.connect(owner).transferOwnership(pendingOwner.address);
      expect(await escrow.pendingOwner()).to.equal(pendingOwner.address);
      await expect(escrow.connect(outsider).acceptOwnership())
        .to.be.revertedWithCustomError(escrow, "NotPendingOwner");
      await escrow.connect(pendingOwner).acceptOwnership();
      expect(await escrow.owner()).to.equal(pendingOwner.address);
    });

    it("allows only the owner to manage agent and verifier authorisation", async function () {
      await expect(escrow.connect(outsider).setAgentAuthorised(outsider.address, true))
        .to.be.revertedWithCustomError(escrow, "NotOwner");
      await expect(escrow.connect(outsider).setVerifierAuthorised(outsider.address, true))
        .to.be.revertedWithCustomError(escrow, "NotOwner");
    });

    it("rejects direct native-token transfers", async function () {
      await expect(owner.sendTransaction({ to: await escrow.getAddress(), value: 1n }))
        .to.be.revertedWithCustomError(escrow, "NativeValueNotAccepted");
    });
  });

  describe("job funding and claiming", function () {
    it("creates a fully funded job and locks its commitments", async function () {
      const clientBefore = await token.balanceOf(client.address);
      const { jobId, budget, expiresAt } = await createJob();
      const job = await escrow.getJob(jobId);

      expect(job.client).to.equal(client.address);
      expect(job.verifier).to.equal(verifier.address);
      expect(job.budget).to.equal(budget);
      expect(job.expiresAt).to.equal(expiresAt);
      expect(job.status).to.equal(1n); // Funded
      expect(await escrow.totalEscrowed()).to.equal(budget);
      expect(await token.balanceOf(await escrow.getAddress())).to.equal(budget);
      expect(await token.balanceOf(client.address)).to.equal(clientBefore - budget);
    });

    it("rejects zero budget, zero commitments, bad expiry, and unauthorised verifier", async function () {
      const expiresAt = (await latestTimestamp()) + 3600;
      await expect(escrow.connect(client).createJob(
        ethers.ZeroAddress, verifier.address, 0, expiresAt, HASH("r"), HASH("t"), HASH("p")
      )).to.be.revertedWithCustomError(escrow, "ZeroAmount");

      await expect(escrow.connect(client).createJob(
        ethers.ZeroAddress, verifier.address, USDC(1), expiresAt, ZERO_HASH, HASH("t"), HASH("p")
      )).to.be.revertedWithCustomError(escrow, "ZeroHash");

      await expect(escrow.connect(client).createJob(
        ethers.ZeroAddress, verifier.address, USDC(1), (await latestTimestamp()) + 60, HASH("r"), HASH("t"), HASH("p")
      )).to.be.revertedWithCustomError(escrow, "InvalidExpiry");

      await expect(escrow.connect(client).createJob(
        ethers.ZeroAddress, outsider.address, USDC(1), expiresAt, HASH("r"), HASH("t"), HASH("p")
      )).to.be.revertedWithCustomError(escrow, "VerifierNotAuthorised");
    });

    it("rejects fee-on-transfer funding instead of under-collateralising the job", async function () {
      await token.setFeeBps(100);
      const expiresAt = (await latestTimestamp()) + 2 * 24 * 60 * 60;
      await expect(escrow.connect(client).createJob(
        ethers.ZeroAddress, verifier.address, USDC(50), expiresAt, HASH("repo"), HASH("task"), HASH("policy")
      )).to.be.revertedWithCustomError(escrow, "UnexpectedReceivedAmount");
      expect(await escrow.jobCount()).to.equal(0n);
      expect(await escrow.totalEscrowed()).to.equal(0n);
    });

    it("allows an authorised agent to claim an open job", async function () {
      const { jobId } = await createJob();
      await expect(escrow.connect(agent).claimJob(jobId))
        .to.emit(escrow, "JobClaimed");
      const job = await escrow.getJob(jobId);
      expect(job.claimDeadline).to.be.greaterThan(0n);
      expect(job.provider).to.equal(agent.address);
      expect(job.status).to.equal(2n); // Claimed
    });

    it("rejects a client inviting itself as the provider", async function () {
      await escrow.connect(owner).setAgentAuthorised(client.address, true);
      const expiresAt = (await latestTimestamp()) + 2 * 24 * 60 * 60;
      await expect(escrow.connect(client).createJob(
        client.address, verifier.address, USDC(50), expiresAt, HASH("repo"), HASH("task"), HASH("policy")
      )).to.be.revertedWithCustomError(escrow, "ClientCannotBeProvider");
    });

    it("enforces independent client, worker, and verifier roles", async function () {
      const expiresAt = (await latestTimestamp()) + 2 * 24 * 60 * 60;
      await escrow.connect(owner).setVerifierAuthorised(client.address, true);
      await expect(escrow.connect(client).createJob(
        ethers.ZeroAddress, client.address, USDC(50), expiresAt, HASH("repo-a"), HASH("task-a"), HASH("policy-a")
      )).to.be.revertedWithCustomError(escrow, "VerifierCannotBeClient");

      await escrow.connect(owner).setAgentAuthorised(verifier.address, true);
      await expect(escrow.connect(client).createJob(
        verifier.address, verifier.address, USDC(50), expiresAt, HASH("repo-b"), HASH("task-b"), HASH("policy-b")
      )).to.be.revertedWithCustomError(escrow, "VerifierCannotBeProvider");

      const { jobId } = await createJob();
      await expect(escrow.connect(verifier).claimJob(jobId))
        .to.be.revertedWithCustomError(escrow, "VerifierCannotBeProvider");
    });

    it("enforces invited-agent and authorisation restrictions", async function () {
      const { jobId } = await createJob({ invitedProvider: agent.address });
      await expect(escrow.connect(agent2).claimJob(jobId))
        .to.be.revertedWithCustomError(escrow, "NotProvider");
      await expect(escrow.connect(outsider).claimJob(jobId))
        .to.be.revertedWithCustomError(escrow, "AgentNotAuthorised");
      await escrow.connect(agent).claimJob(jobId);
    });

    it("prevents a client from claiming their own job", async function () {
      await escrow.connect(owner).setAgentAuthorised(client.address, true);
      const { jobId } = await createJob();
      await expect(escrow.connect(client).claimJob(jobId))
        .to.be.revertedWithCustomError(escrow, "ClientCannotBeProvider");
    });

    it("lets the client cancel only an unclaimed job and receive a full refund", async function () {
      const { jobId, budget } = await createJob();
      const before = await token.balanceOf(client.address);
      await expect(escrow.connect(client).cancelUnclaimedJob(jobId))
        .to.emit(escrow, "JobCancelled")
        .withArgs(jobId, client.address, budget);
      expect(await token.balanceOf(client.address)).to.equal(before + budget);
      expect((await escrow.getJob(jobId)).status).to.equal(6n); // Cancelled
      expect(await escrow.totalEscrowed()).to.equal(0n);
    });

    it("does not allow cancellation after an agent claims", async function () {
      const { jobId } = await createJob();
      await escrow.connect(agent).claimJob(jobId);
      await expect(escrow.connect(client).cancelUnclaimedJob(jobId))
        .to.be.revertedWithCustomError(escrow, "InvalidJobStatus");
    });
  });

  describe("submission", function () {
    it("records the exact commit, pull request, and canonical deliverable hash", async function () {
      const { jobId } = await createJob();
      await escrow.connect(agent).claimJob(jobId);
      const commitHash = HASH("real-commit");
      const pr = 91;
      const expected = await escrow.computeDeliverableHash(jobId, commitHash, pr);

      await expect(escrow.connect(agent).submitWork(jobId, commitHash, pr))
        .to.emit(escrow, "WorkSubmitted")
        .withArgs(jobId, agent.address, expected, commitHash, pr);

      const job = await escrow.getJob(jobId);
      expect(job.deliverableHash).to.equal(expected);
      expect(job.commitHash).to.equal(commitHash);
      expect(job.pullRequestNumber).to.equal(pr);
      expect(job.status).to.equal(3n); // Submitted
    });

    it("allows only the assigned provider to submit", async function () {
      const { jobId } = await createJob();
      await escrow.connect(agent).claimJob(jobId);
      await expect(escrow.connect(agent2).submitWork(jobId, HASH("x"), 1))
        .to.be.revertedWithCustomError(escrow, "NotProvider");
    });

    it("rejects empty commit or pull-request commitments", async function () {
      const { jobId } = await createJob();
      await escrow.connect(agent).claimJob(jobId);
      await expect(escrow.connect(agent).submitWork(jobId, ZERO_HASH, 1))
        .to.be.revertedWithCustomError(escrow, "ZeroHash");
      await expect(escrow.connect(agent).submitWork(jobId, HASH("x"), 0))
        .to.be.revertedWithCustomError(escrow, "PullRequestNumberRequired");
    });

    it("rejects submissions after the deadline", async function () {
      const { jobId } = await createJob({ duration: 3600 });
      await escrow.connect(agent).claimJob(jobId);
      await increaseTime(3601);
      await expect(escrow.connect(agent).submitWork(jobId, HASH("late"), 1))
        .to.be.revertedWithCustomError(escrow, "ClaimWindowClosed");
    });

    it("blocks a claimed agent after its authorisation is revoked", async function () {
      const { jobId } = await createJob();
      await escrow.connect(agent).claimJob(jobId);
      await escrow.connect(owner).setAgentAuthorised(agent.address, false);
      await expect(escrow.connect(agent).submitWork(jobId, HASH("revoked-agent"), 7))
        .to.be.revertedWithCustomError(escrow, "AgentNotAuthorised");
    });
  });

  describe("successful verification and Karma", function () {
    it("pays the exact agent, closes escrow, and awards Karma", async function () {
      const { jobId, budget } = await createJob();
      const { deliverableHash } = await claimAndSubmit(jobId);
      const evidenceHash = HASH("verification-report");
      const agentBefore = await token.balanceOf(agent.address);

      await expect(escrow.connect(verifier).verifyAndPay(jobId, deliverableHash, evidenceHash))
        .to.emit(escrow, "JobCompleted");

      expect(await token.balanceOf(agent.address)).to.equal(agentBefore + budget);
      expect(await escrow.totalEscrowed()).to.equal(0n);
      expect((await escrow.getJob(jobId)).status).to.equal(4n); // Completed
      expect(await escrow.completedJobs(agent.address)).to.equal(1n);
      expect(await escrow.totalEarned(agent.address)).to.equal(budget);
      expect(await escrow.karmaScore(agent.address)).to.equal(100n);
    });

    it("awards Karma once per unique client while counting every completed job", async function () {
      for (let i = 0; i < 2; i++) {
        const { jobId } = await createJob();
        const { deliverableHash } = await claimAndSubmit(jobId, agent, `commit-${i}`, 20 + i);
        await escrow.connect(verifier).verifyAndPay(jobId, deliverableHash, HASH(`report-${i}`));
      }
      expect(await escrow.completedJobs(agent.address)).to.equal(2n);
      expect(await escrow.karmaScore(agent.address)).to.equal(100n);
    });

    it("awards additional Karma when a genuinely different client is served", async function () {
      const first = await createJob();
      const firstProof = await claimAndSubmit(first.jobId, agent, "first-client", 41);
      await escrow.connect(verifier).verifyAndPay(first.jobId, firstProof.deliverableHash, HASH("first-report"));

      await token.mint(outsider.address, USDC(100));
      await token.connect(outsider).approve(await escrow.getAddress(), ethers.MaxUint256);
      const expiresAt = (await latestTimestamp()) + 2 * 24 * 60 * 60;
      await escrow.connect(outsider).createJob(
        agent.address,
        verifier.address,
        USDC(50),
        expiresAt,
        HASH("repo-second-client"),
        HASH("task-second-client"),
        HASH("policy-second-client")
      );
      const secondJobId = await escrow.jobCount();
      const secondProof = await claimAndSubmit(secondJobId, agent, "second-client", 42);
      await escrow.connect(verifier).verifyAndPay(secondJobId, secondProof.deliverableHash, HASH("second-report"));

      expect(await escrow.completedJobs(agent.address)).to.equal(2n);
      expect(await escrow.karmaScore(agent.address)).to.equal(200n);
    });

    it("records a completed low-value job without awarding Karma", async function () {
      const { jobId, budget } = await createJob({ budget: USDC("0.5") });
      const { deliverableHash } = await claimAndSubmit(jobId);
      await escrow.connect(verifier).verifyAndPay(jobId, deliverableHash, HASH("report"));
      expect(await escrow.completedJobs(agent.address)).to.equal(1n);
      expect(await escrow.totalEarned(agent.address)).to.equal(budget);
      expect(await escrow.karmaScore(agent.address)).to.equal(0n);
    });

    it("blocks a verifier immediately after its authorisation is revoked", async function () {
      const { jobId } = await createJob();
      const { deliverableHash } = await claimAndSubmit(jobId);
      await escrow.connect(owner).setVerifierAuthorised(verifier.address, false);
      await expect(escrow.connect(verifier).verifyAndPay(jobId, deliverableHash, HASH("existing-job-report")))
        .to.be.revertedWithCustomError(escrow, "VerifierNotAuthorised");
      expect((await escrow.getJob(jobId)).status).to.equal(3n);
    });

    it("allows verification after submission deadline but within the grace period", async function () {
      const { jobId } = await createJob({ duration: 3600 });
      const { deliverableHash } = await claimAndSubmit(jobId);
      await increaseTime(3601);
      await escrow.connect(verifier).verifyAndPay(jobId, deliverableHash, HASH("grace-report"));
      expect((await escrow.getJob(jobId)).status).to.equal(4n);
    });

    it("binds verification evidence to this job, deliverable, verdict, and report", async function () {
      const { jobId } = await createJob();
      const { deliverableHash } = await claimAndSubmit(jobId);
      const reportHash = HASH("bound-report");
      const expectedEvidence = await escrow.computeEvidenceHash(
        jobId, deliverableHash, reportHash, true, ZERO_HASH
      );
      await escrow.connect(verifier).verifyAndPay(jobId, deliverableHash, reportHash);
      const job = await escrow.getJob(jobId);
      expect(job.reportHash).to.equal(reportHash);
      expect(job.evidenceHash).to.equal(expectedEvidence);
    });

    it("requires the exact job verifier and exact deliverable", async function () {
      const { jobId } = await createJob();
      const { deliverableHash } = await claimAndSubmit(jobId);
      await expect(escrow.connect(verifier2).verifyAndPay(jobId, deliverableHash, HASH("r")))
        .to.be.revertedWithCustomError(escrow, "NotVerifier");
      await expect(escrow.connect(verifier).verifyAndPay(jobId, HASH("wrong"), HASH("r")))
        .to.be.revertedWithCustomError(escrow, "DeliverableMismatch");
    });

    it("cannot pay a job twice", async function () {
      const { jobId } = await createJob();
      const { deliverableHash } = await claimAndSubmit(jobId);
      await escrow.connect(verifier).verifyAndPay(jobId, deliverableHash, HASH("r"));
      await expect(escrow.connect(verifier).verifyAndPay(jobId, deliverableHash, HASH("r2")))
        .to.be.revertedWithCustomError(escrow, "InvalidJobStatus");
    });

    it("rolls back all state if the token payout fails", async function () {
      const { jobId, budget } = await createJob();
      const { deliverableHash } = await claimAndSubmit(jobId);
      await token.setTransfersRevert(true);
      await expect(escrow.connect(verifier).verifyAndPay(jobId, deliverableHash, HASH("r"))).to.be.reverted;
      const job = await escrow.getJob(jobId);
      expect(job.status).to.equal(3n); // Submitted
      expect(await escrow.totalEscrowed()).to.equal(budget);
      expect(await escrow.karmaScore(agent.address)).to.equal(0n);
      expect(await escrow.completedJobs(agent.address)).to.equal(0n);
    });
  });

  describe("rejection and refunds", function () {
    it("lets only the verifier reject the exact submission and atomically refunds the client", async function () {
      const { jobId, budget } = await createJob();
      const { deliverableHash } = await claimAndSubmit(jobId);
      const clientBefore = await token.balanceOf(client.address);

      await expect(escrow.connect(verifier).rejectAndRefund(
        jobId, deliverableHash, HASH("failed-test-report"), HASH("hidden-tests-failed")
      )).to.emit(escrow, "JobRejected");

      expect(await token.balanceOf(client.address)).to.equal(clientBefore + budget);
      expect((await escrow.getJob(jobId)).status).to.equal(5n); // Rejected
      expect(await escrow.failedJobs(agent.address)).to.equal(1n);
      expect(await escrow.totalEscrowed()).to.equal(0n);
      expect(await escrow.karmaScore(agent.address)).to.equal(0n);
    });

    it("rejects wrong verifier, wrong deliverable, and empty evidence", async function () {
      const { jobId } = await createJob();
      const { deliverableHash } = await claimAndSubmit(jobId);
      await expect(escrow.connect(verifier2).rejectAndRefund(jobId, deliverableHash, HASH("e"), HASH("r")))
        .to.be.revertedWithCustomError(escrow, "NotVerifier");
      await expect(escrow.connect(verifier).rejectAndRefund(jobId, HASH("wrong"), HASH("e"), HASH("r")))
        .to.be.revertedWithCustomError(escrow, "DeliverableMismatch");
      await expect(escrow.connect(verifier).rejectAndRefund(jobId, deliverableHash, ZERO_HASH, HASH("r")))
        .to.be.revertedWithCustomError(escrow, "ZeroHash");
    });

    it("refunds an unclaimed expired job and a stale claimed job", async function () {
      const first = await createJob({ duration: 3600 });
      const second = await createJob({ duration: 3600 });
      await escrow.connect(agent).claimJob(second.jobId);
      await increaseTime(3601);

      await escrow.connect(client).claimExpiredRefund(first.jobId);
      await escrow.connect(client).refundAbandonedClaim(second.jobId);
      expect((await escrow.getJob(first.jobId)).status).to.equal(8n); // Expired
      expect((await escrow.getJob(second.jobId)).status).to.equal(7n); // Abandoned
      expect(await escrow.abandonedJobs(agent.address)).to.equal(1n);
      expect(await escrow.totalEscrowed()).to.equal(0n);
    });

    it("protects a submitted job during the verifier grace period, then allows expiry refund", async function () {
      const { jobId } = await createJob({ duration: 3600 });
      await claimAndSubmit(jobId);
      await increaseTime(3601);
      await expect(escrow.connect(client).claimExpiredRefund(jobId))
        .to.be.revertedWithCustomError(escrow, "VerificationWindowOpen");
      await increaseTime(grace);
      await escrow.connect(client).claimExpiredRefund(jobId);
      expect((await escrow.getJob(jobId)).status).to.equal(8n);
    });

    it("starts the verifier timeout at submission instead of the far-away job deadline", async function () {
      const { jobId, expiresAt } = await createJob({ duration: 30 * 24 * 60 * 60 });
      await claimAndSubmit(jobId);
      const deadline = await escrow.verificationDeadline(jobId);
      expect(deadline).to.be.lessThan(BigInt(expiresAt));
      await increaseTime(grace + 1);
      await escrow.connect(client).claimExpiredRefund(jobId);
      expect((await escrow.getJob(jobId)).status).to.equal(8n);
    });

    it("refunds a stale claim before a long job reaches its final expiry", async function () {
      const { jobId, expiresAt } = await createJob({ duration: 10 * 24 * 60 * 60 });
      await escrow.connect(agent).claimJob(jobId);
      const job = await escrow.getJob(jobId);
      expect(job.claimDeadline).to.be.lessThan(BigInt(expiresAt));
      await expect(escrow.connect(client).refundAbandonedClaim(jobId))
        .to.be.revertedWithCustomError(escrow, "ClaimWindowOpen");
      await increaseTime(claimPeriod + 1);
      await escrow.connect(client).refundAbandonedClaim(jobId);
      expect((await escrow.getJob(jobId)).status).to.equal(7n);
      expect(await escrow.abandonedJobs(agent.address)).to.equal(1n);
    });

    it("prevents early, unauthorised, and duplicate refunds", async function () {
      const { jobId } = await createJob({ duration: 3600 });
      await expect(escrow.connect(client).claimExpiredRefund(jobId))
        .to.be.revertedWithCustomError(escrow, "JobNotExpired");
      await increaseTime(3601);
      await expect(escrow.connect(outsider).claimExpiredRefund(jobId))
        .to.be.revertedWithCustomError(escrow, "NotClient");
      await escrow.connect(client).claimExpiredRefund(jobId);
      await expect(escrow.connect(client).claimExpiredRefund(jobId))
        .to.be.revertedWithCustomError(escrow, "InvalidJobStatus");
    });
  });

  describe("pause and fund safety", function () {
    it("pause blocks new work actions but never blocks client cancellation/refund", async function () {
      const open = await createJob();
      const expiring = await createJob({ duration: 3600 });
      await escrow.connect(owner).setPaused(true);

      const expiresAt = (await latestTimestamp()) + 2 * 24 * 60 * 60;
      await expect(escrow.connect(client).createJob(
        ethers.ZeroAddress, verifier.address, USDC(50), expiresAt, HASH("paused-repo"), HASH("paused-task"), HASH("paused-policy")
      )).to.be.revertedWithCustomError(escrow, "ContractPaused");
      await expect(escrow.connect(agent).claimJob(open.jobId))
        .to.be.revertedWithCustomError(escrow, "ContractPaused");

      await escrow.connect(client).cancelUnclaimedJob(open.jobId);
      await increaseTime(3601);
      await escrow.connect(client).claimExpiredRefund(expiring.jobId);
    });

    it("blocks a malicious payment token from re-entering job creation", async function () {
      const ReentrantToken = await ethers.getContractFactory("MockReentrantUSDC");
      const reentrantToken = await ReentrantToken.deploy();
      await reentrantToken.waitForDeployment();

      const Escrow = await ethers.getContractFactory("VeyraJobEscrow");
      const guardedEscrow = await Escrow.deploy(await reentrantToken.getAddress(), owner.address, USDC(1), grace, claimPeriod);
      await guardedEscrow.waitForDeployment();
      await guardedEscrow.connect(owner).setVerifierAuthorised(verifier.address, true);

      await reentrantToken.mint(client.address, USDC(100));
      await reentrantToken.connect(client).approve(await guardedEscrow.getAddress(), ethers.MaxUint256);

      const expiresAt = (await latestTimestamp()) + 2 * 24 * 60 * 60;
      const attackData = guardedEscrow.interface.encodeFunctionData("createJob", [
        ethers.ZeroAddress, verifier.address, USDC(1), expiresAt, HASH("attack-repo"), HASH("attack-task"), HASH("attack-policy")
      ]);
      await reentrantToken.configureAttack(await guardedEscrow.getAddress(), attackData, true);

      await guardedEscrow.connect(client).createJob(
        ethers.ZeroAddress, verifier.address, USDC(50), expiresAt, HASH("repo"), HASH("task"), HASH("policy")
      );

      expect(await reentrantToken.reentrySucceeded()).to.equal(false);
      expect(await guardedEscrow.jobCount()).to.equal(1n);
      expect(await guardedEscrow.totalEscrowed()).to.equal(USDC(50));
    });

    it("blocks cross-function reentrancy during an agent payout", async function () {
      const ReentrantToken = await ethers.getContractFactory("MockReentrantUSDC");
      const reentrantToken = await ReentrantToken.deploy();
      await reentrantToken.waitForDeployment();

      const Escrow = await ethers.getContractFactory("VeyraJobEscrow");
      const guardedEscrow = await Escrow.deploy(
        await reentrantToken.getAddress(), owner.address, USDC(1), grace, claimPeriod
      );
      await guardedEscrow.waitForDeployment();
      await guardedEscrow.connect(owner).setAgentAuthorised(agent.address, true);
      await guardedEscrow.connect(owner).setAgentAuthorised(await reentrantToken.getAddress(), true);
      await guardedEscrow.connect(owner).setVerifierAuthorised(verifier.address, true);

      await reentrantToken.mint(client.address, USDC(200));
      await reentrantToken.connect(client).approve(await guardedEscrow.getAddress(), ethers.MaxUint256);
      const expiresAt = (await latestTimestamp()) + 2 * 24 * 60 * 60;

      await guardedEscrow.connect(client).createJob(
        agent.address, verifier.address, USDC(50), expiresAt,
        HASH("pay-repo"), HASH("pay-task"), HASH("pay-policy")
      );
      const payJobId = await guardedEscrow.jobCount();
      await guardedEscrow.connect(client).createJob(
        ethers.ZeroAddress, verifier.address, USDC(50), expiresAt,
        HASH("open-repo"), HASH("open-task"), HASH("open-policy")
      );
      const openJobId = await guardedEscrow.jobCount();

      await guardedEscrow.connect(agent).claimJob(payJobId);
      const commitHash = HASH("reentry-proof");
      await guardedEscrow.connect(agent).submitWork(payJobId, commitHash, 55);
      const deliverableHash = await guardedEscrow.computeDeliverableHash(payJobId, commitHash, 55);

      const attackData = guardedEscrow.interface.encodeFunctionData("claimJob", [openJobId]);
      await reentrantToken.configureAttack(await guardedEscrow.getAddress(), attackData, true);
      await guardedEscrow.connect(verifier).verifyAndPay(payJobId, deliverableHash, HASH("safe-report"));

      expect(await reentrantToken.reentrySucceeded()).to.equal(false);
      expect((await guardedEscrow.getJob(openJobId)).status).to.equal(1n); // Funded
    });

    it("keeps token balance equal to active escrow across mixed job outcomes", async function () {
      const completed = await createJob({ budget: USDC(10) });
      const rejected = await createJob({ budget: USDC(20) });
      const stillActive = await createJob({ budget: USDC(30) });

      const firstProof = await claimAndSubmit(completed.jobId, agent, "completed", 101);
      await escrow.connect(verifier).verifyAndPay(completed.jobId, firstProof.deliverableHash, HASH("completed-report"));

      const secondProof = await claimAndSubmit(rejected.jobId, agent2, "rejected", 102);
      await escrow.connect(verifier).rejectAndRefund(
        rejected.jobId, secondProof.deliverableHash, HASH("rejected-report"), HASH("failed-policy")
      );

      expect(await escrow.totalEscrowed()).to.equal(USDC(30));
      expect(await token.balanceOf(await escrow.getAddress())).to.equal(USDC(30));
      expect((await escrow.getJob(stillActive.jobId)).status).to.equal(1n);
    });

    it("never permits a rejected job to be paid or refunded twice", async function () {
      const { jobId } = await createJob();
      const { deliverableHash } = await claimAndSubmit(jobId);
      await escrow.connect(verifier).rejectAndRefund(
        jobId, deliverableHash, HASH("evidence"), HASH("reason")
      );
      await expect(escrow.connect(verifier).verifyAndPay(jobId, deliverableHash, HASH("later")))
        .to.be.revertedWithCustomError(escrow, "InvalidJobStatus");
      await expect(escrow.connect(client).claimExpiredRefund(jobId))
        .to.be.revertedWithCustomError(escrow, "InvalidJobStatus");
    });

    it("prevents verification or rejection once the grace period has ended", async function () {
      const { jobId } = await createJob({ duration: 3600 });
      const { deliverableHash } = await claimAndSubmit(jobId);
      await increaseTime(3601 + grace);
      await expect(escrow.connect(verifier).verifyAndPay(jobId, deliverableHash, HASH("late")))
        .to.be.revertedWithCustomError(escrow, "JobExpiredAlready");
      await expect(escrow.connect(verifier).rejectAndRefund(jobId, deliverableHash, HASH("late"), HASH("reason")))
        .to.be.revertedWithCustomError(escrow, "JobExpiredAlready");
    });

    it("owner can recover accidental excess USDC but cannot touch active escrow", async function () {
      const { jobId, budget } = await createJob();
      await token.mint(await escrow.getAddress(), USDC(3));

      await expect(escrow.connect(owner).recoverExcessPaymentToken(owner.address, USDC(4)))
        .to.be.revertedWithCustomError(escrow, "InsufficientExcessBalance");
      await escrow.connect(owner).recoverExcessPaymentToken(owner.address, USDC(3));
      expect(await token.balanceOf(await escrow.getAddress())).to.equal(budget);
      expect(await escrow.totalEscrowed()).to.equal(budget);
      expect((await escrow.getJob(jobId)).status).to.equal(1n);
    });
  });
});
