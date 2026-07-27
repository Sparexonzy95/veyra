from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from workers.hosted_agent_connection import runtime_is_online
from workers.models import HostedAgentConnection, WorkerAgent


class Command(BaseCommand):
    help = "Show the connected independent verifier-agent status."

    def handle(self, *args, **options):
        verifier = (
            WorkerAgent.objects.filter(
                agent_role=WorkerAgent.AgentRole.VERIFIER,
                status=WorkerAgent.Status.ACTIVE,
            )
            .select_related("hosted_connection")
            .order_by("created_at")
            .first()
        )
        if verifier is None:
            raise CommandError(
                "No active verifier agent exists. Start port 9200 and run connect_verifier_agent."
            )
        try:
            connection = verifier.hosted_connection
        except HostedAgentConnection.DoesNotExist as exc:
            raise CommandError("The verifier agent has no hosted runtime connection.") from exc
        self.stdout.write(f"Name: {verifier.name}")
        self.stdout.write(f"Agent ID: {verifier.id}")
        self.stdout.write(f"Role: {verifier.agent_role}")
        self.stdout.write(f"Status: {verifier.status}")
        self.stdout.write(f"Runtime ID: {connection.runtime_id}")
        self.stdout.write(f"Runtime URL: {connection.runtime_url}")
        self.stdout.write(f"Signing key fingerprint: {connection.public_key_fingerprint}")
        self.stdout.write(f"Provider: {connection.provider}")
        self.stdout.write(f"Model: {connection.model_name}")
        self.stdout.write(f"Last heartbeat: {connection.last_seen_at or 'Never'}")
        self.stdout.write(f"Online: {runtime_is_online(connection)}")
        self.stdout.write(f"Checked at: {timezone.now().isoformat()}")
        if runtime_is_online(connection):
            self.stdout.write(self.style.SUCCESS("Independent verifier runtime is ready."))
        else:
            raise CommandError("The verifier runtime is connected but offline.")
