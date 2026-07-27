from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache
from eth_account import Account
from eth_account.messages import encode_defunct
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied

from workers.models import RunnerDevice


SIGNATURE_VERSION = "VEYRA-RUNNER-V1"
PAIRING_SIGNATURE_VERSION = "VEYRA-RUNNER-PAIR-V1"


@dataclass
class RunnerPrincipal:
    device: RunnerDevice

    @property
    def is_authenticated(self):
        return True

    @property
    def is_active(self):
        return self.device.status == RunnerDevice.Status.ACTIVE

    def __str__(self):
        return f"runner:{self.device.id}"


def canonical_pairing_message(*, code: str, device_address: str, runner_name: str) -> str:
    normalised_code = "".join(ch for ch in code.upper() if ch.isalnum())
    return "\n".join(
        [
            PAIRING_SIGNATURE_VERSION,
            normalised_code,
            device_address.lower(),
            runner_name.strip(),
        ]
    )


def canonical_runner_message(*, method: str, path: str, timestamp: str, nonce: str, body: bytes) -> str:
    body_hash = hashlib.sha256(body).hexdigest()
    return "\n".join(
        [
            SIGNATURE_VERSION,
            method.upper(),
            path,
            timestamp,
            nonce,
            body_hash,
        ]
    )


class RunnerSignatureAuthentication(BaseAuthentication):
    """Verify an EIP-191 signature from the Runner's local device keypair."""

    def authenticate(self, request):
        runner_id = request.headers.get("X-Veyra-Runner-ID", "").strip()
        timestamp = request.headers.get("X-Veyra-Timestamp", "").strip()
        nonce = request.headers.get("X-Veyra-Nonce", "").strip()
        signature = request.headers.get("X-Veyra-Signature", "").strip()

        if not any((runner_id, timestamp, nonce, signature)):
            return None
        if not all((runner_id, timestamp, nonce, signature)):
            raise AuthenticationFailed("Runner signature headers are incomplete.")

        try:
            timestamp_value = int(timestamp)
        except ValueError as exc:
            raise AuthenticationFailed("Runner timestamp is invalid.") from exc

        max_skew = getattr(settings, "VEYRA_RUNNER_SIGNATURE_MAX_SKEW_SECONDS", 300)
        if abs(int(time.time()) - timestamp_value) > max_skew:
            raise AuthenticationFailed("Runner signature timestamp is outside the allowed window.")

        if len(nonce) < 16 or len(nonce) > 128:
            raise AuthenticationFailed("Runner nonce is invalid.")

        try:
            runner = RunnerDevice.objects.select_related("owner_user").get(id=runner_id)
        except (RunnerDevice.DoesNotExist, ValueError) as exc:
            raise AuthenticationFailed("Runner device is unknown.") from exc

        if runner.status != RunnerDevice.Status.ACTIVE:
            raise AuthenticationFailed("Runner device has been revoked.")

        message = canonical_runner_message(
            method=request.method,
            path=request.path,
            timestamp=timestamp,
            nonce=nonce,
            body=request.body,
        )
        try:
            recovered = Account.recover_message(
                encode_defunct(text=message),
                signature=signature,
            ).lower()
        except Exception as exc:
            raise AuthenticationFailed("Runner signature is invalid.") from exc

        if recovered != runner.device_address.lower():
            raise AuthenticationFailed("Runner signature does not match the registered device.")

        nonce_key = f"veyra:runner-nonce:{runner.id}:{hashlib.sha256(nonce.encode()).hexdigest()}"
        if not cache.add(nonce_key, True, timeout=max_skew * 2):
            raise PermissionDenied("Runner request was already used.")

        principal = RunnerPrincipal(device=runner)
        return principal, runner

    def authenticate_header(self, request):
        return SIGNATURE_VERSION
