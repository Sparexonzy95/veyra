from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import secrets
import socket
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from workers.models import HostedAgentConnection, WorkerAgent


class HostedAgentConnectionError(RuntimeError):
    """Raised when an owner-hosted agent runtime cannot be connected safely."""


@dataclass(frozen=True)
class ParsedConnectionLink:
    runtime_base_url: str
    one_time_token: str
    protocol_version: int


@dataclass(frozen=True)
class RuntimeClaimResult:
    connection_id: str
    runtime_id: str
    runtime_url: str
    provider: str
    model: str
    runtime_version: str
    protocol_version: int
    capabilities: dict[str, Any]


def _safe_message(exc: Exception) -> str:
    message = str(exc or "").strip() or exc.__class__.__name__
    for secret_name in ("CIRCLE_API_KEY", "CIRCLE_ENTITY_SECRET"):
        value = str(getattr(settings, secret_name, "") or "")
        if value:
            message = message.replace(value, "[REDACTED]")
    return message[:800]


def _b64decode(value: str) -> bytes:
    value = str(value or "").strip()
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(value + padding)
    except Exception as exc:
        raise HostedAgentConnectionError("The runtime returned invalid signing data.") from exc


def _credential_hash(raw_token: str) -> str:
    secret = settings.SECRET_KEY.encode("utf-8")
    return hmac.new(secret, raw_token.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_runtime_credential(connection: HostedAgentConnection, raw_token: str) -> bool:
    raw_token = str(raw_token or "").strip()
    if not raw_token or not connection.credential_hash:
        return False
    return hmac.compare_digest(connection.credential_hash, _credential_hash(raw_token))


def _host_addresses(hostname: str) -> set[ipaddress._BaseAddress]:
    try:
        return {
            ipaddress.ip_address(item[4][0])
            for item in socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
        }
    except OSError as exc:
        raise HostedAgentConnectionError("The hosted-agent server address could not be resolved.") from exc


def _is_private_address(address: ipaddress._BaseAddress) -> bool:
    return bool(
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def _validate_runtime_host(hostname: str) -> None:
    hostname = str(hostname or "").strip().lower()
    if not hostname:
        raise HostedAgentConnectionError("The connection link has no hosted-agent address.")

    allow_local = bool(
        getattr(settings, "VEYRA_ALLOW_LOCAL_AGENT_RUNTIME", False)
        and settings.DEBUG
    )
    local_names = {"localhost", "127.0.0.1", "::1"}
    if hostname in local_names:
        if not allow_local:
            raise HostedAgentConnectionError(
                "Local agent servers are disabled. Use a public HTTPS hosted-agent address."
            )
        return

    addresses = _host_addresses(hostname)
    if any(_is_private_address(address) for address in addresses):
        if not allow_local:
            raise HostedAgentConnectionError(
                "Private or local network addresses are not allowed for hosted agents."
            )


def parse_connection_link(value: str) -> ParsedConnectionLink:
    """Parse the copy/paste connection link produced by a hosted runtime.

    Supported format:
      veyra-connect://host[:port]/connect/<one-time-token>?protocol=1
    """

    raw = str(value or "").strip()
    if not raw:
        raise HostedAgentConnectionError("Paste the Veyra connection link from the hosted agent server.")
    if len(raw) > 2000:
        raise HostedAgentConnectionError("The hosted-agent connection link is too long.")

    parsed = urlparse(raw)
    if parsed.scheme != "veyra-connect":
        raise HostedAgentConnectionError(
            "The connection link must begin with veyra-connect://"
        )
    try:
        username = parsed.username
        password = parsed.password
        hostname = parsed.hostname or ""
    except ValueError as exc:
        raise HostedAgentConnectionError("The hosted-agent address is malformed.") from exc
    if username or password:
        raise HostedAgentConnectionError("Credentials are not allowed inside the runtime address.")
    if parsed.fragment:
        raise HostedAgentConnectionError("The connection link must not contain a URL fragment.")

    _validate_runtime_host(hostname)

    segments = [unquote(segment) for segment in parsed.path.split("/") if segment]
    if len(segments) != 2 or segments[0] != "connect":
        raise HostedAgentConnectionError(
            "The connection link must end with /connect/<one-time-token>."
        )
    token = segments[1].strip()
    if not 24 <= len(token) <= 256:
        raise HostedAgentConnectionError("The one-time connection token is invalid.")
    if any(character.isspace() for character in token):
        raise HostedAgentConnectionError("The one-time connection token is invalid.")

    query = parse_qs(parsed.query)
    try:
        protocol_version = int((query.get("protocol") or ["1"])[0])
    except (TypeError, ValueError) as exc:
        raise HostedAgentConnectionError("The connection protocol version is invalid.") from exc

    supported = int(getattr(settings, "VEYRA_AGENT_CONNECTION_PROTOCOL_VERSION", 1))
    if protocol_version != supported:
        raise HostedAgentConnectionError(
            f"This runtime uses protocol {protocol_version}, but Veyra requires protocol {supported}."
        )

    try:
        port = parsed.port
    except ValueError as exc:
        raise HostedAgentConnectionError("The hosted-agent port is invalid.") from exc
    local_host = hostname.lower() in {"localhost", "127.0.0.1", "::1"}
    scheme = "http" if local_host else "https"
    netloc = f"[{hostname}]" if ":" in hostname and not hostname.startswith("[") else hostname
    if port:
        netloc = f"{netloc}:{port}"

    return ParsedConnectionLink(
        runtime_base_url=f"{scheme}://{netloc}",
        one_time_token=token,
        protocol_version=protocol_version,
    )


def _signature_message(*, challenge: str, runtime_id: str) -> bytes:
    return f"veyra-connect-v1:{challenge}:{runtime_id}".encode("utf-8")


def _validate_challenge_payload(payload: Any, *, challenge: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise HostedAgentConnectionError("The hosted agent returned an invalid challenge response.")

    runtime_id = str(payload.get("runtime_id") or "").strip()
    returned_challenge = str(payload.get("challenge") or "").strip()
    public_key_text = str(payload.get("public_key") or "").strip()
    signature_text = str(payload.get("signature") or "").strip()
    runtime_version = str(payload.get("runtime_version") or "").strip()
    provider = str(payload.get("provider") or "").strip()
    model_name = str(payload.get("model") or "").strip()
    try:
        protocol_version = int(payload.get("protocol_version") or 0)
    except (TypeError, ValueError) as exc:
        raise HostedAgentConnectionError(
            "The hosted agent returned an invalid connection protocol."
        ) from exc
    provider_ready = bool(payload.get("provider_ready"))
    capabilities = payload.get("capabilities") or {}

    if not runtime_id or len(runtime_id) > 160:
        raise HostedAgentConnectionError("The hosted agent returned no valid runtime identity.")
    if returned_challenge != challenge:
        raise HostedAgentConnectionError("The hosted agent returned the wrong verification challenge.")
    if not public_key_text or not signature_text:
        raise HostedAgentConnectionError("The hosted agent did not prove ownership of its connection link.")
    if not runtime_version:
        raise HostedAgentConnectionError("The hosted agent did not report its runtime version.")
    if not provider or not model_name:
        raise HostedAgentConnectionError("The hosted agent did not report its AI provider and model.")
    if protocol_version != int(getattr(settings, "VEYRA_AGENT_CONNECTION_PROTOCOL_VERSION", 1)):
        raise HostedAgentConnectionError("The hosted agent uses an unsupported connection protocol.")
    if not provider_ready:
        detail = str(payload.get("provider_message") or "The owner-managed AI provider is not ready.")
        raise HostedAgentConnectionError(detail[:600])
    if not isinstance(capabilities, dict):
        raise HostedAgentConnectionError("The hosted agent returned invalid capability metadata.")

    public_key_raw = _b64decode(public_key_text)
    signature_raw = _b64decode(signature_text)
    if len(public_key_raw) != 32:
        raise HostedAgentConnectionError("The hosted agent returned an invalid Ed25519 public key.")

    try:
        Ed25519PublicKey.from_public_bytes(public_key_raw).verify(
            signature_raw,
            _signature_message(challenge=challenge, runtime_id=runtime_id),
        )
    except (InvalidSignature, ValueError) as exc:
        raise HostedAgentConnectionError(
            "The hosted agent failed cryptographic ownership verification."
        ) from exc

    return {
        "runtime_id": runtime_id,
        "public_key": public_key_text,
        "public_key_fingerprint": hashlib.sha256(public_key_raw).hexdigest(),
        "runtime_version": runtime_version[:64],
        "provider": provider[:80],
        "model": model_name[:160],
        "protocol_version": protocol_version,
        "provider_ready": True,
        "capabilities": capabilities,
        "provider_message": str(payload.get("provider_message") or "")[:240],
    }


def connect_hosted_agent(
    *,
    worker: WorkerAgent,
    connection_link: str,
    client: httpx.Client | None = None,
) -> RuntimeClaimResult:
    """Verify a one-time runtime link and exchange it for a long-lived credential."""

    worker.refresh_from_db()
    parsed = parse_connection_link(connection_link)
    challenge = secrets.token_urlsafe(32)
    timeout = float(getattr(settings, "VEYRA_AGENT_CONNECTION_TIMEOUT_SECONDS", 20))
    owns_client = client is None
    http_client = client or httpx.Client(timeout=timeout, follow_redirects=False)

    try:
        challenge_response = http_client.post(
            f"{parsed.runtime_base_url}/veyra/connect/challenge",
            json={
                "token": parsed.one_time_token,
                "challenge": challenge,
                "veyra_origin": str(getattr(settings, "VEYRA_PUBLIC_API_URL", "")).rstrip("/"),
            },
            headers={"User-Agent": "Veyra-Control-Plane/1"},
        )
        if challenge_response.status_code != 200:
            detail = ""
            try:
                detail = str(challenge_response.json().get("detail") or "")
            except Exception:
                detail = ""
            raise HostedAgentConnectionError(
                detail or f"Hosted-agent verification failed ({challenge_response.status_code})."
            )
        try:
            challenge_payload = challenge_response.json()
        except ValueError as exc:
            raise HostedAgentConnectionError(
                "The hosted agent returned an invalid verification response."
            ) from exc
        verified = _validate_challenge_payload(challenge_payload, challenge=challenge)

        # Reject an already-owned runtime before sending the final claim. This
        # prevents a copied link from replacing another agent's live credential.
        with transaction.atomic():
            if HostedAgentConnection.objects.select_for_update().filter(
                runtime_id=verified["runtime_id"]
            ).exclude(worker=worker).exists():
                raise HostedAgentConnectionError(
                    "This hosted runtime is already connected to another Veyra agent."
                )
            if HostedAgentConnection.objects.select_for_update().filter(
                public_key_fingerprint=verified["public_key_fingerprint"]
            ).exclude(worker=worker).exists():
                raise HostedAgentConnectionError(
                    "This hosted runtime signing key is already connected to another Veyra agent."
                )
            existing_connection = (
                HostedAgentConnection.objects.select_for_update()
                .filter(worker=worker)
                .first()
            )
            if (
                existing_connection
                and existing_connection.status != HostedAgentConnection.Status.REVOKED
                and existing_connection.runtime_id
                and existing_connection.runtime_id != verified["runtime_id"]
            ):
                raise HostedAgentConnectionError(
                    "This agent is already connected to a different hosted runtime. Disconnect it before connecting another one."
                )

        runtime_credential = secrets.token_urlsafe(48)
        api_base_url = str(
            getattr(settings, "VEYRA_PUBLIC_API_URL", "http://127.0.0.1:8000")
        ).rstrip("/")
        heartbeat_url = api_base_url + "/api/v1/agent-runtime/heartbeat/"
        configuration_url = api_base_url + "/api/v1/agent-runtime/configuration/"
        claim_response = http_client.post(
            f"{parsed.runtime_base_url}/veyra/connect/claim",
            json={
                "token": parsed.one_time_token,
                "agent_id": str(worker.id),
                "agent_name": worker.name,
                "runtime_credential": runtime_credential,
                "heartbeat_url": heartbeat_url,
                "configuration_url": configuration_url,
                "protocol_version": parsed.protocol_version,
            },
            headers={"User-Agent": "Veyra-Control-Plane/1"},
        )
        if claim_response.status_code not in {200, 201}:
            detail = ""
            try:
                detail = str(claim_response.json().get("detail") or "")
            except Exception:
                detail = ""
            raise HostedAgentConnectionError(
                detail or f"Hosted-agent claim failed ({claim_response.status_code})."
            )
        try:
            claim_payload = claim_response.json()
        except ValueError as exc:
            raise HostedAgentConnectionError(
                "The hosted agent returned an invalid claim response."
            ) from exc
        if not isinstance(claim_payload, dict) or not claim_payload.get("connected"):
            raise HostedAgentConnectionError("The hosted agent did not confirm the secure connection.")

        with transaction.atomic():
            connection, _ = HostedAgentConnection.objects.select_for_update().get_or_create(
                worker=worker,
                defaults={
                    "runtime_id": verified["runtime_id"],
                    "runtime_url": parsed.runtime_base_url,
                    "public_key": verified["public_key"],
                    "public_key_fingerprint": verified["public_key_fingerprint"],
                    "protocol_version": verified["protocol_version"],
                    "runtime_version": verified["runtime_version"],
                    "provider": verified["provider"],
                    "model_name": verified["model"],
                    "credential_hash": _credential_hash(runtime_credential),
                    "status": HostedAgentConnection.Status.CONNECTED,
                    "connected_at": timezone.now(),
                    "last_seen_at": timezone.now(),
                },
            )
            if (
                connection.status == HostedAgentConnection.Status.CONNECTED
                and connection.runtime_id
                and connection.runtime_id != verified["runtime_id"]
            ):
                raise HostedAgentConnectionError(
                    "This agent is already connected to a different hosted runtime."
                )
            connection.runtime_id = verified["runtime_id"]
            connection.runtime_url = parsed.runtime_base_url
            connection.public_key = verified["public_key"]
            connection.public_key_fingerprint = verified["public_key_fingerprint"]
            connection.protocol_version = verified["protocol_version"]
            connection.runtime_version = verified["runtime_version"]
            connection.provider = verified["provider"]
            connection.model_name = verified["model"]
            connection.provider_ready = True
            connection.capabilities = verified["capabilities"]
            connection.credential_hash = _credential_hash(runtime_credential)
            connection.status = HostedAgentConnection.Status.CONNECTED
            connection.connected_at = timezone.now()
            connection.last_seen_at = timezone.now()
            connection.last_error = ""
            connection.metadata = {
                "provider_message": verified["provider_message"],
                "connection_method": "COPY_LINK_V1",
            }
            connection.save()

            locked_worker = WorkerAgent.objects.select_for_update().get(pk=worker.pk)
            locked_worker.engine_provider = WorkerAgent.EngineProvider.CUSTOM
            locked_worker.engine_model = verified["model"]
            locked_worker.engine_connected = True
            locked_worker.engine_version = verified["runtime_version"]
            locked_worker.engine_last_checked_at = timezone.now()
            locked_worker.engine_last_error = ""
            locked_worker.engine_connection_metadata = {
                "runtime_id": verified["runtime_id"],
                "provider": verified["provider"],
                "model": verified["model"],
                "protocol_version": verified["protocol_version"],
                "public_key_fingerprint": verified["public_key_fingerprint"],
                "capabilities": verified["capabilities"],
            }
            locked_worker.status = WorkerAgent.Status.RUNTIME_CONNECTED
            locked_worker.save(
                update_fields=[
                    "engine_provider",
                    "engine_model",
                    "engine_connected",
                    "engine_version",
                    "engine_last_checked_at",
                    "engine_last_error",
                    "engine_connection_metadata",
                    "status",
                    "updated_at",
                ]
            )
    except HostedAgentConnectionError:
        raise
    except httpx.RequestError as exc:
        raise HostedAgentConnectionError(
            f"Veyra could not reach the hosted-agent server: {_safe_message(exc)}"
        ) from exc
    finally:
        if owns_client:
            http_client.close()

    return RuntimeClaimResult(
        connection_id=str(connection.id),
        runtime_id=connection.runtime_id,
        runtime_url=connection.runtime_url,
        provider=connection.provider,
        model=connection.model_name,
        runtime_version=connection.runtime_version,
        protocol_version=connection.protocol_version,
        capabilities=connection.capabilities,
    )


def mark_runtime_heartbeat(
    *,
    connection: HostedAgentConnection,
    payload: dict[str, Any],
) -> HostedAgentConnection:
    provider_ready = bool(payload.get("provider_ready", True))
    health = str(payload.get("health") or "HEALTHY").upper().strip()
    runtime_version = str(payload.get("runtime_version") or connection.runtime_version).strip()
    model_name = str(payload.get("model") or connection.model_name).strip()
    message = str(payload.get("message") or "").strip()[:240]

    connection.provider_ready = provider_ready
    connection.runtime_version = runtime_version[:64]
    connection.model_name = model_name[:160]
    connection.last_seen_at = timezone.now()
    connection.last_error = "" if health == "HEALTHY" and provider_ready else message
    connection.status = (
        HostedAgentConnection.Status.CONNECTED
        if health == "HEALTHY" and provider_ready
        else HostedAgentConnection.Status.UNHEALTHY
    )
    connection.save(
        update_fields=[
            "provider_ready",
            "runtime_version",
            "model_name",
            "last_seen_at",
            "last_error",
            "status",
            "updated_at",
        ]
    )

    worker = connection.worker
    worker.engine_provider = WorkerAgent.EngineProvider.CUSTOM
    worker.engine_model = connection.model_name or worker.engine_model
    worker.engine_version = connection.runtime_version or worker.engine_version
    worker.engine_connected = connection.status == HostedAgentConnection.Status.CONNECTED
    worker.engine_last_checked_at = connection.last_seen_at
    worker.engine_last_error = connection.last_error
    worker.save(
        update_fields=[
            "engine_provider",
            "engine_model",
            "engine_version",
            "engine_connected",
            "engine_last_checked_at",
            "engine_last_error",
            "updated_at",
        ]
    )
    return connection


def runtime_is_online(connection: HostedAgentConnection) -> bool:
    if connection.status != HostedAgentConnection.Status.CONNECTED:
        return False
    if connection.last_seen_at is None:
        return False
    window = timedelta(
        seconds=int(getattr(settings, "VEYRA_AGENT_RUNTIME_ONLINE_WINDOW_SECONDS", 35))
    )
    return timezone.now() - connection.last_seen_at <= window
