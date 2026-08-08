// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "./interfaces/IERC20.sol";
import {SafeERC20} from "./libraries/SafeERC20.sol";

/// @title VeyraJobEscrow
/// @notice USDC escrow for autonomous software jobs on Arc.
/// @dev A client funds a job, an authorised agent submits an exact code
///      commitment, and an independent authorised verifier either pays the
///      agent or refunds the client. Karma is informational only and never
///      influences settlement permissions.
contract VeyraJobEscrow {
    using SafeERC20 for IERC20;

    enum JobStatus {
        None,
        Funded,
        Claimed,
        Submitted,
        Completed,
        Rejected,
        Cancelled,
        Abandoned,
        Expired
    }

    struct Job {
        address client;
        address invitedProvider;
        address provider;
        address verifier;
        uint256 budget;
        uint256 expiresAt;
        uint256 claimDeadline;
        bytes32 repositoryHash;
        bytes32 taskHash;
        bytes32 policyHash;
        bytes32 deliverableHash;
        bytes32 commitHash;
        uint64 pullRequestNumber;
        bytes32 reportHash;
        bytes32 evidenceHash;
        bytes32 rejectionReasonHash;
        JobStatus status;
        uint64 createdAt;
        uint64 claimedAt;
        uint64 submittedAt;
        uint64 resolvedAt;
    }

    uint256 public constant KARMA_PER_UNIQUE_CLIENT = 100;
    uint256 public constant MIN_JOB_DURATION = 10 minutes;
    uint256 public constant MAX_JOB_DURATION = 90 days;
    uint256 public constant MIN_VERIFICATION_GRACE_PERIOD = 10 minutes;
    uint256 public constant MAX_VERIFICATION_GRACE_PERIOD = 7 days;
    uint256 public constant MIN_CLAIM_SUBMISSION_PERIOD = 10 minutes;
    uint256 public constant MAX_CLAIM_SUBMISSION_PERIOD = 30 days;

    bytes32 private constant DELIVERABLE_DOMAIN = keccak256("VEYRA_DELIVERABLE_V1");
    bytes32 private constant EVIDENCE_DOMAIN = keccak256("VEYRA_EVIDENCE_V1");

    IERC20 public immutable paymentToken;
    uint256 public immutable minimumKarmaBudget;
    uint256 public immutable verificationGracePeriod;
    uint256 public immutable claimSubmissionPeriod;

    address public owner;
    address public pendingOwner;
    bool public paused;
    uint256 public jobCount;
    uint256 public totalEscrowed;

    mapping(uint256 jobId => Job job) private _jobs;
    mapping(address account => bool authorised) public authorisedAgents;
    mapping(address account => bool authorised) public authorisedVerifiers;

    mapping(address agent => uint256 score) public karmaScore;
    mapping(address agent => uint256 count) public completedJobs;
    mapping(address agent => uint256 count) public failedJobs;
    mapping(address agent => uint256 count) public abandonedJobs;
    mapping(address agent => uint256 amount) public totalEarned;
    mapping(address client => mapping(address agent => bool awarded)) public karmaAwardedByClient;

    bool private _entered;

    event OwnershipTransferStarted(address indexed previousOwner, address indexed pendingOwner);
    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);
    event Paused(address indexed account);
    event Unpaused(address indexed account);
    event AgentAuthorisationUpdated(address indexed agent, bool authorised);
    event VerifierAuthorisationUpdated(address indexed verifier, bool authorised);

    event JobCreated(
        uint256 indexed jobId,
        address indexed client,
        address indexed verifier,
        address invitedProvider,
        uint256 budget,
        uint256 expiresAt,
        bytes32 repositoryHash,
        bytes32 taskHash,
        bytes32 policyHash
    );
    event JobClaimed(uint256 indexed jobId, address indexed provider, uint256 claimDeadline);
    event WorkSubmitted(
        uint256 indexed jobId,
        address indexed provider,
        bytes32 indexed deliverableHash,
        bytes32 commitHash,
        uint64 pullRequestNumber
    );
    event JobCompleted(
        uint256 indexed jobId,
        address indexed provider,
        address indexed verifier,
        bytes32 deliverableHash,
        bytes32 reportHash,
        bytes32 evidenceHash,
        uint256 amountPaid,
        uint256 karmaAwarded
    );
    event JobRejected(
        uint256 indexed jobId,
        address indexed provider,
        address indexed verifier,
        bytes32 deliverableHash,
        bytes32 reportHash,
        bytes32 evidenceHash,
        bytes32 reasonHash,
        uint256 amountRefunded
    );
    event JobCancelled(uint256 indexed jobId, address indexed client, uint256 amountRefunded);
    event ClaimAbandoned(
        uint256 indexed jobId,
        address indexed provider,
        address indexed client,
        uint256 amountRefunded
    );
    event JobExpired(uint256 indexed jobId, address indexed client, uint256 amountRefunded);
    event KarmaAwarded(uint256 indexed jobId, address indexed provider, uint256 amount, uint256 newScore);
    event ExcessTokenRecovered(address indexed token, address indexed recipient, uint256 amount);

    error ZeroAddress();
    error ZeroAmount();
    error ZeroHash();
    error NotContract();
    error NotOwner();
    error NotPendingOwner();
    error ContractPaused();
    error NotClient();
    error NotProvider();
    error NotVerifier();
    error AgentNotAuthorised();
    error VerifierNotAuthorised();
    error ClientCannotBeProvider();
    error VerifierCannotBeClient();
    error VerifierCannotBeProvider();
    error InvalidExpiry();
    error InvalidVerificationGracePeriod();
    error InvalidClaimSubmissionPeriod();
    error InvalidJob();
    error InvalidJobStatus(JobStatus expected, JobStatus actual);
    error JobExpiredAlready();
    error JobNotExpired();
    error ClaimWindowOpen();
    error ClaimWindowClosed();
    error VerificationWindowOpen();
    error DeliverableMismatch();
    error PullRequestNumberRequired();
    error UnexpectedReceivedAmount(uint256 expected, uint256 received);
    error InsufficientExcessBalance();
    error ReentrantCall();
    error NativeValueNotAccepted();

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }

    modifier whenNotPaused() {
        if (paused) revert ContractPaused();
        _;
    }

    modifier nonReentrant() {
        if (_entered) revert ReentrantCall();
        _entered = true;
        _;
        _entered = false;
    }

    constructor(
        address paymentTokenAddress,
        address initialOwner,
        uint256 minimumKarmaBudget_,
        uint256 verificationGracePeriod_,
        uint256 claimSubmissionPeriod_
    ) {
        if (paymentTokenAddress == address(0) || initialOwner == address(0)) revert ZeroAddress();
        if (paymentTokenAddress.code.length == 0) revert NotContract();
        if (minimumKarmaBudget_ == 0) revert ZeroAmount();
        if (
            verificationGracePeriod_ < MIN_VERIFICATION_GRACE_PERIOD ||
            verificationGracePeriod_ > MAX_VERIFICATION_GRACE_PERIOD
        ) revert InvalidVerificationGracePeriod();
        if (
            claimSubmissionPeriod_ < MIN_CLAIM_SUBMISSION_PERIOD ||
            claimSubmissionPeriod_ > MAX_CLAIM_SUBMISSION_PERIOD
        ) revert InvalidClaimSubmissionPeriod();

        paymentToken = IERC20(paymentTokenAddress);
        owner = initialOwner;
        minimumKarmaBudget = minimumKarmaBudget_;
        verificationGracePeriod = verificationGracePeriod_;
        claimSubmissionPeriod = claimSubmissionPeriod_;

        emit OwnershipTransferred(address(0), initialOwner);
    }

    receive() external payable {
        revert NativeValueNotAccepted();
    }

    fallback() external payable {
        revert NativeValueNotAccepted();
    }

    function transferOwnership(address newOwner) external onlyOwner {
        if (newOwner == address(0)) revert ZeroAddress();
        pendingOwner = newOwner;
        emit OwnershipTransferStarted(owner, newOwner);
    }

    function acceptOwnership() external {
        if (msg.sender != pendingOwner) revert NotPendingOwner();
        address previousOwner = owner;
        owner = msg.sender;
        pendingOwner = address(0);
        emit OwnershipTransferred(previousOwner, msg.sender);
    }

    function setPaused(bool shouldPause) external onlyOwner {
        paused = shouldPause;
        if (shouldPause) emit Paused(msg.sender);
        else emit Unpaused(msg.sender);
    }

    function setAgentAuthorised(address agent, bool authorised) external onlyOwner {
        if (agent == address(0)) revert ZeroAddress();
        authorisedAgents[agent] = authorised;
        emit AgentAuthorisationUpdated(agent, authorised);
    }

    function setVerifierAuthorised(address verifier, bool authorised) external onlyOwner {
        if (verifier == address(0)) revert ZeroAddress();
        authorisedVerifiers[verifier] = authorised;
        emit VerifierAuthorisationUpdated(verifier, authorised);
    }

    /// @notice Creates and fully funds a Veyra job in one transaction.
    /// @param invitedProvider Zero for any authorised agent, otherwise the only agent allowed to claim.
    function createJob(
        address invitedProvider,
        address verifier,
        uint256 budget,
        uint256 expiresAt,
        bytes32 repositoryHash,
        bytes32 taskHash,
        bytes32 policyHash
    ) external whenNotPaused nonReentrant returns (uint256 jobId) {
        if (verifier == address(0)) revert ZeroAddress();
        if (!authorisedVerifiers[verifier]) revert VerifierNotAuthorised();
        if (verifier == msg.sender) revert VerifierCannotBeClient();
        if (budget == 0) revert ZeroAmount();
        if (repositoryHash == bytes32(0) || taskHash == bytes32(0) || policyHash == bytes32(0)) {
            revert ZeroHash();
        }
        if (expiresAt < block.timestamp + MIN_JOB_DURATION || expiresAt > block.timestamp + MAX_JOB_DURATION) {
            revert InvalidExpiry();
        }
        if (invitedProvider != address(0)) {
            if (!authorisedAgents[invitedProvider]) revert AgentNotAuthorised();
            if (invitedProvider == msg.sender) revert ClientCannotBeProvider();
            if (invitedProvider == verifier) revert VerifierCannotBeProvider();
        }

        uint256 balanceBefore = paymentToken.balanceOf(address(this));
        paymentToken.safeTransferFrom(msg.sender, address(this), budget);
        uint256 received = paymentToken.balanceOf(address(this)) - balanceBefore;
        if (received != budget) revert UnexpectedReceivedAmount(budget, received);

        jobId = ++jobCount;
        Job storage job = _jobs[jobId];
        job.client = msg.sender;
        job.invitedProvider = invitedProvider;
        job.verifier = verifier;
        job.budget = budget;
        job.expiresAt = expiresAt;
        job.repositoryHash = repositoryHash;
        job.taskHash = taskHash;
        job.policyHash = policyHash;
        job.status = JobStatus.Funded;
        job.createdAt = uint64(block.timestamp);

        totalEscrowed += budget;

        emit JobCreated(
            jobId,
            msg.sender,
            verifier,
            invitedProvider,
            budget,
            expiresAt,
            repositoryHash,
            taskHash,
            policyHash
        );
    }

    function claimJob(uint256 jobId) external whenNotPaused nonReentrant {
        Job storage job = _requireJob(jobId);
        _requireStatus(job, JobStatus.Funded);
        if (block.timestamp >= job.expiresAt) revert JobExpiredAlready();
        if (!authorisedAgents[msg.sender]) revert AgentNotAuthorised();
        if (msg.sender == job.client) revert ClientCannotBeProvider();
        if (msg.sender == job.verifier) revert VerifierCannotBeProvider();
        if (job.invitedProvider != address(0) && msg.sender != job.invitedProvider) revert NotProvider();

        uint256 proposedClaimDeadline = block.timestamp + claimSubmissionPeriod;
        uint256 claimDeadline = proposedClaimDeadline < job.expiresAt ? proposedClaimDeadline : job.expiresAt;

        job.provider = msg.sender;
        job.claimDeadline = claimDeadline;
        job.status = JobStatus.Claimed;
        job.claimedAt = uint64(block.timestamp);

        emit JobClaimed(jobId, msg.sender, claimDeadline);
    }

    function computeDeliverableHash(
        uint256 jobId,
        bytes32 commitHash,
        uint64 pullRequestNumber
    ) public view returns (bytes32) {
        Job storage job = _requireJobView(jobId);
        if (commitHash == bytes32(0)) revert ZeroHash();
        if (pullRequestNumber == 0) revert PullRequestNumberRequired();

        return keccak256(
            abi.encode(
                DELIVERABLE_DOMAIN,
                block.chainid,
                address(this),
                jobId,
                job.repositoryHash,
                job.taskHash,
                job.policyHash,
                commitHash,
                pullRequestNumber
            )
        );
    }

    function computeEvidenceHash(
        uint256 jobId,
        bytes32 deliverableHash,
        bytes32 reportHash,
        bool approved,
        bytes32 reasonHash
    ) public view returns (bytes32) {
        _requireJobView(jobId);
        if (deliverableHash == bytes32(0) || reportHash == bytes32(0)) revert ZeroHash();
        return keccak256(
            abi.encode(
                EVIDENCE_DOMAIN,
                block.chainid,
                address(this),
                jobId,
                deliverableHash,
                reportHash,
                approved,
                reasonHash
            )
        );
    }

    function submitWork(
        uint256 jobId,
        bytes32 commitHash,
        uint64 pullRequestNumber
    ) external whenNotPaused nonReentrant {
        Job storage job = _requireJob(jobId);
        _requireStatus(job, JobStatus.Claimed);
        if (msg.sender != job.provider) revert NotProvider();
        if (!authorisedAgents[msg.sender]) revert AgentNotAuthorised();
        if (block.timestamp > job.claimDeadline) revert ClaimWindowClosed();

        bytes32 deliverableHash = computeDeliverableHash(jobId, commitHash, pullRequestNumber);
        job.commitHash = commitHash;
        job.pullRequestNumber = pullRequestNumber;
        job.deliverableHash = deliverableHash;
        job.status = JobStatus.Submitted;
        job.submittedAt = uint64(block.timestamp);

        emit WorkSubmitted(jobId, msg.sender, deliverableHash, commitHash, pullRequestNumber);
    }

    function verifyAndPay(
        uint256 jobId,
        bytes32 deliverableHash,
        bytes32 reportHash
    ) external whenNotPaused nonReentrant {
        Job storage job = _requireJob(jobId);
        _requireStatus(job, JobStatus.Submitted);
        if (msg.sender != job.verifier) revert NotVerifier();
        if (!authorisedVerifiers[msg.sender]) revert VerifierNotAuthorised();
        if (deliverableHash != job.deliverableHash) revert DeliverableMismatch();
        if (reportHash == bytes32(0)) revert ZeroHash();
        if (block.timestamp > _verificationDeadline(job)) revert JobExpiredAlready();

        bytes32 evidenceHash = _computeEvidenceHash(jobId, deliverableHash, reportHash, true, bytes32(0));
        uint256 amount = job.budget;
        job.reportHash = reportHash;
        job.evidenceHash = evidenceHash;
        job.status = JobStatus.Completed;
        job.resolvedAt = uint64(block.timestamp);
        totalEscrowed -= amount;

        completedJobs[job.provider] += 1;
        totalEarned[job.provider] += amount;

        uint256 karmaAwarded;
        if (amount >= minimumKarmaBudget && !karmaAwardedByClient[job.client][job.provider]) {
            karmaAwardedByClient[job.client][job.provider] = true;
            karmaAwarded = KARMA_PER_UNIQUE_CLIENT;
            karmaScore[job.provider] += karmaAwarded;
            emit KarmaAwarded(jobId, job.provider, karmaAwarded, karmaScore[job.provider]);
        }

        paymentToken.safeTransfer(job.provider, amount);

        emit JobCompleted(
            jobId,
            job.provider,
            msg.sender,
            deliverableHash,
            reportHash,
            evidenceHash,
            amount,
            karmaAwarded
        );
    }

    /// @notice Rejects a submitted job and atomically refunds its client.
    function rejectAndRefund(
        uint256 jobId,
        bytes32 deliverableHash,
        bytes32 reportHash,
        bytes32 reasonHash
    ) external whenNotPaused nonReentrant {
        Job storage job = _requireJob(jobId);
        _requireStatus(job, JobStatus.Submitted);
        if (msg.sender != job.verifier) revert NotVerifier();
        if (!authorisedVerifiers[msg.sender]) revert VerifierNotAuthorised();
        if (deliverableHash != job.deliverableHash) revert DeliverableMismatch();
        if (reportHash == bytes32(0) || reasonHash == bytes32(0)) revert ZeroHash();
        if (block.timestamp > _verificationDeadline(job)) revert JobExpiredAlready();

        bytes32 evidenceHash = _computeEvidenceHash(jobId, deliverableHash, reportHash, false, reasonHash);
        uint256 amount = job.budget;
        job.reportHash = reportHash;
        job.evidenceHash = evidenceHash;
        job.rejectionReasonHash = reasonHash;
        job.status = JobStatus.Rejected;
        job.resolvedAt = uint64(block.timestamp);
        totalEscrowed -= amount;
        failedJobs[job.provider] += 1;

        paymentToken.safeTransfer(job.client, amount);

        emit JobRejected(
            jobId,
            job.provider,
            msg.sender,
            deliverableHash,
            reportHash,
            evidenceHash,
            reasonHash,
            amount
        );
    }

    function cancelUnclaimedJob(uint256 jobId) external nonReentrant {
        Job storage job = _requireJob(jobId);
        _requireStatus(job, JobStatus.Funded);
        if (msg.sender != job.client) revert NotClient();

        uint256 amount = job.budget;
        job.status = JobStatus.Cancelled;
        job.resolvedAt = uint64(block.timestamp);
        totalEscrowed -= amount;
        paymentToken.safeTransfer(job.client, amount);

        emit JobCancelled(jobId, job.client, amount);
    }

    /// @notice Refunds a client when an agent claims a job but does not submit
    ///         before the fixed claim deadline.
    function refundAbandonedClaim(uint256 jobId) external nonReentrant {
        Job storage job = _requireJob(jobId);
        _requireStatus(job, JobStatus.Claimed);
        if (msg.sender != job.client) revert NotClient();
        if (block.timestamp <= job.claimDeadline) revert ClaimWindowOpen();

        uint256 amount = job.budget;
        job.status = JobStatus.Abandoned;
        job.resolvedAt = uint64(block.timestamp);
        totalEscrowed -= amount;
        abandonedJobs[job.provider] += 1;

        paymentToken.safeTransfer(job.client, amount);

        emit ClaimAbandoned(jobId, job.provider, job.client, amount);
    }

    /// @notice Refunds an unclaimed job after its deadline, or a submitted job
    ///         after its verifier window has elapsed.
    function claimExpiredRefund(uint256 jobId) external nonReentrant {
        Job storage job = _requireJob(jobId);
        if (msg.sender != job.client) revert NotClient();

        if (job.status == JobStatus.Funded) {
            if (block.timestamp <= job.expiresAt) revert JobNotExpired();
        } else if (job.status == JobStatus.Submitted) {
            if (block.timestamp <= _verificationDeadline(job)) revert VerificationWindowOpen();
        } else {
            revert InvalidJobStatus(JobStatus.Funded, job.status);
        }

        uint256 amount = job.budget;
        job.status = JobStatus.Expired;
        job.resolvedAt = uint64(block.timestamp);
        totalEscrowed -= amount;
        paymentToken.safeTransfer(job.client, amount);

        emit JobExpired(jobId, job.client, amount);
    }

    function recoverForeignToken(address token, address recipient, uint256 amount) external onlyOwner nonReentrant {
        if (token == address(0) || recipient == address(0)) revert ZeroAddress();
        if (token == address(paymentToken)) revert InsufficientExcessBalance();
        IERC20(token).safeTransfer(recipient, amount);
        emit ExcessTokenRecovered(token, recipient, amount);
    }

    /// @notice Recovers only payment tokens that are not backing active jobs.
    function recoverExcessPaymentToken(address recipient, uint256 amount) external onlyOwner nonReentrant {
        if (recipient == address(0)) revert ZeroAddress();
        uint256 balance = paymentToken.balanceOf(address(this));
        uint256 excess = balance > totalEscrowed ? balance - totalEscrowed : 0;
        if (amount == 0 || amount > excess) revert InsufficientExcessBalance();
        paymentToken.safeTransfer(recipient, amount);
        emit ExcessTokenRecovered(address(paymentToken), recipient, amount);
    }

    function getJob(uint256 jobId) external view returns (Job memory) {
        return _requireJobView(jobId);
    }

    function verificationDeadline(uint256 jobId) external view returns (uint256) {
        Job storage job = _requireJobView(jobId);
        if (job.status != JobStatus.Submitted) revert InvalidJobStatus(JobStatus.Submitted, job.status);
        return _verificationDeadline(job);
    }

    function escrowBalance() external view returns (uint256) {
        return paymentToken.balanceOf(address(this));
    }

    function isSolvent() external view returns (bool) {
        return paymentToken.balanceOf(address(this)) >= totalEscrowed;
    }

    function _verificationDeadline(Job storage job) private view returns (uint256) {
        return uint256(job.submittedAt) + verificationGracePeriod;
    }

    function _computeEvidenceHash(
        uint256 jobId,
        bytes32 deliverableHash,
        bytes32 reportHash,
        bool approved,
        bytes32 reasonHash
    ) private view returns (bytes32) {
        return keccak256(
            abi.encode(
                EVIDENCE_DOMAIN,
                block.chainid,
                address(this),
                jobId,
                deliverableHash,
                reportHash,
                approved,
                reasonHash
            )
        );
    }

    function _requireJob(uint256 jobId) private view returns (Job storage job) {
        job = _jobs[jobId];
        if (job.status == JobStatus.None) revert InvalidJob();
    }

    function _requireJobView(uint256 jobId) private view returns (Job storage job) {
        job = _jobs[jobId];
        if (job.status == JobStatus.None) revert InvalidJob();
    }

    function _requireStatus(Job storage job, JobStatus expected) private view {
        if (job.status != expected) revert InvalidJobStatus(expected, job.status);
    }
}
