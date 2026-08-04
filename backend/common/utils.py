import hashlib
import json
import secrets
from decimal import Decimal, ROUND_DOWN
from django.conf import settings

SENSITIVE_KEYS = {
    'authorization', 'x-user-token', 'usertoken', 'encryptionkey', 'refreshtoken',
    'deviceencryptionkey', 'otp', 'circle_api_key', 'session_token',
}

def random_token(byte_length: int = 32) -> str:
    return secrets.token_urlsafe(byte_length)

def digest_token(raw: str) -> str:
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()

def canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)

def redact_mapping(value):
    if isinstance(value, dict):
        return {
            key: ('[REDACTED]' if key.lower().replace('_', '') in SENSITIVE_KEYS else redact_mapping(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_mapping(item) for item in value]
    return value

def to_atomic_usdc(amount: Decimal) -> int:
    amount = Decimal(str(amount))
    scale = Decimal(10) ** settings.ARC_USDC_DECIMALS
    return int((amount * scale).quantize(Decimal('1'), rounding=ROUND_DOWN))

def from_atomic_usdc(amount: int) -> Decimal:
    return Decimal(amount) / (Decimal(10) ** settings.ARC_USDC_DECIMALS)
