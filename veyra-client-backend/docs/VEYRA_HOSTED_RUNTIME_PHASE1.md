# Veyra Hosted Runtime

## Product decision

The default Veyra experience uses a Veyra-managed runtime. Agent owners do not
install a local Runner, enter a pairing code, open PowerShell, or keep a laptop
online.

The owner flow is now:

```text
Create agent
-> Veyra provisions the hosted runtime automatically
-> Connect GitHub App
-> Create the agent wallet
-> Authorise the worker contract
-> Run qualification
-> Activate the agent
```

Owner-hosted Runner pairing remains in the backend as an advanced architecture
for a later release, but it is not exposed in normal MVP onboarding.

## MVP implementation

The hosted runtime reuses the existing `RunnerDevice` and
`RunnerAgentBinding` control-plane records. Hosted devices are marked through
safe runtime metadata:

```json
{
  "runtime_mode": "VEYRA_HOSTED",
  "managed_by": "VEYRA",
  "workspace": "isolated"
}
```

A hosted runtime:

- is provisioned automatically when an owner creates an agent;
- does not require a one-time pairing code;
- does not depend on owner heartbeats;
- is considered available while its Veyra-managed device record is active and
  healthy;
- starts work in an isolated workspace when a job arrives;
- never exposes Circle, GitHub App, database, or platform secrets to users.

In local development, the Django host represents the Veyra-managed execution
machine. In deployment, this control-plane record must map to a real isolated
container or worker service.

## Existing agent conversion

Migration `0010_provision_veyra_hosted_runtimes` converts existing owner-created
agents to hosted runtime bindings. It:

- creates a Veyra-hosted runtime identity for each agent;
- moves the existing agent binding to that hosted runtime;
- cancels unused pairing codes;
- revokes local Runner devices that no longer host any agents;
- marks the runtime connection ready;
- preserves GitHub, wallet, contract, qualification, and job data.

## Security boundary

The hosted runtime must still receive only the job material needed for execution.
It must not receive:

- Circle entity secrets;
- Circle API keys;
- Veyra database credentials;
- contract owner credentials;
- GitHub App private keys;
- unrelated user files.

GitHub write operations, wallet transactions, Arc settlement, and audit records
remain controlled by Veyra services.

## Next production hardening

The hackathon control-plane implementation should later be backed by:

1. an isolated container per execution;
2. a job queue and worker autoscaling;
3. short-lived job-scoped credentials;
4. network egress restrictions;
5. CPU, memory, disk, and time limits;
6. immutable execution logs;
7. automatic teardown after completion;
8. signed job packages and signed results.
