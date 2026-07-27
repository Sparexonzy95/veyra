from pathlib import Path
import os
import environ
from corsheaders.defaults import default_headers

BASE_DIR = Path(__file__).resolve().parent.parent
env = environ.Env(
    DEBUG=(bool, True),
    SESSION_COOKIE_SECURE=(bool, False),
)
env_file = BASE_DIR / '.env'
if env_file.exists():
    environ.Env.read_env(env_file, overwrite=True)

SECRET_KEY = env('DJANGO_SECRET_KEY', default='dev-only-change-me')
DEBUG = env('DEBUG')
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=['localhost', '127.0.0.1'])

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'corsheaders',
    'rest_framework',
    'drf_spectacular',
    'common',
    'accounts',
    'wallets',
    'jobs',
    'blockchain',
    'workers',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'common.middleware.RequestIdMiddleware',
    'common.middleware.AllowedOriginMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'
TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [],
    'APP_DIRS': True,
    'OPTIONS': {'context_processors': [
        'django.template.context_processors.request',
        'django.contrib.auth.context_processors.auth',
        'django.contrib.messages.context_processors.messages',
    ]},
}]
WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

DATABASES = {
    'default': env.db(
        'DATABASE_URL',
        default=f'sqlite:///{BASE_DIR / "db.sqlite3"}',
    )
}
DATABASES['default']['CONN_MAX_AGE'] = 60

AUTH_PASSWORD_VALIDATORS = []
AUTH_USER_MODEL = 'accounts.User'
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True
STATIC_URL = 'static/'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': ['accounts.authentication.VeyraSessionAuthentication'],
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.IsAuthenticated'],
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'EXCEPTION_HANDLER': 'common.exceptions.api_exception_handler',
    'DEFAULT_RENDERER_CLASSES': ['rest_framework.renderers.JSONRenderer'],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
}
SPECTACULAR_SETTINGS = {
    'TITLE': 'Veyra Backend API',
    'DESCRIPTION': 'Django backend for Veyra client and worker actors.',
    'VERSION': '0.1.0',
}

CORS_ALLOWED_ORIGINS = env.list('CORS_ALLOWED_ORIGINS', default=['http://localhost:3000'])
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = [*default_headers, 'x-circle-user-token']
VEYRA_ALLOWED_ORIGINS = set(CORS_ALLOWED_ORIGINS)
CSRF_TRUSTED_ORIGINS = CORS_ALLOWED_ORIGINS

SESSION_COOKIE_SECURE = env('SESSION_COOKIE_SECURE')

SECURE_SSL_REDIRECT = env.bool('SECURE_SSL_REDIRECT', default=False)
SECURE_HSTS_SECONDS = env.int('SECURE_HSTS_SECONDS', default=0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool('SECURE_HSTS_INCLUDE_SUBDOMAINS', default=False)
SECURE_HSTS_PRELOAD = env.bool('SECURE_HSTS_PRELOAD', default=False)
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE

VEYRA_SESSION_COOKIE = env('VEYRA_SESSION_COOKIE', default='veyra_session')
VEYRA_ONBOARDING_COOKIE = env('VEYRA_ONBOARDING_COOKIE', default='veyra_onboarding')
VEYRA_SESSION_TTL_SECONDS = env.int('VEYRA_SESSION_TTL_SECONDS', default=60 * 60 * 24 * 7)
VEYRA_ONBOARDING_TTL_SECONDS = env.int('VEYRA_ONBOARDING_TTL_SECONDS', default=60 * 30)
VEYRA_COOKIE_SAMESITE = env('VEYRA_COOKIE_SAMESITE', default='Lax')

CIRCLE_BASE_URL = env('CIRCLE_BASE_URL', default='https://api.circle.com')
CIRCLE_API_KEY = env('CIRCLE_API_KEY', default='')
CIRCLE_ENTITY_SECRET = env('CIRCLE_ENTITY_SECRET', default='')
CIRCLE_APP_ID = env('CIRCLE_APP_ID', default='')
CIRCLE_TIMEOUT_SECONDS = env.int('CIRCLE_TIMEOUT_SECONDS', default=20)

ARC_RPC_URL = env('ARC_RPC_URL', default='https://rpc.testnet.arc.network')
ARC_CHAIN_ID = env.int('ARC_CHAIN_ID', default=5042002)
ARC_BLOCKCHAIN = env('ARC_BLOCKCHAIN', default='ARC-TESTNET')
VEYRA_CONTRACT_ADDRESS = env('VEYRA_CONTRACT_ADDRESS', default='0xe422ba48559A4ef5B1fad8A5AAc4F646b252d9F5')
ARC_USDC_ADDRESS = env('ARC_USDC_ADDRESS', default='0x3600000000000000000000000000000000000000')
ARC_USDC_DECIMALS = env.int('ARC_USDC_DECIMALS', default=6)
VEYRA_VERIFIER_ADDRESS = env('VEYRA_VERIFIER_ADDRESS', default='0x0EdBC6F8506e72478CE78a4AE934C7b21cb7050A')
ARC_INDEXER_START_BLOCK = env.int('ARC_INDEXER_START_BLOCK', default=0)
ARC_TRANSACTION_SYNC_MIN_INTERVAL_SECONDS = env.int('ARC_TRANSACTION_SYNC_MIN_INTERVAL_SECONDS', default=2)

GITHUB_API_URL = env('GITHUB_API_URL', default='https://api.github.com')
GITHUB_TOKEN = env('GITHUB_TOKEN', default='')  # legacy fallback only
GITHUB_APP_ID = env('GITHUB_APP_ID', default='')
GITHUB_APP_SLUG = env('GITHUB_APP_SLUG', default='')
GITHUB_APP_PRIVATE_KEY = env('GITHUB_APP_PRIVATE_KEY', default='')
GITHUB_APP_PRIVATE_KEY_PATH = env('GITHUB_APP_PRIVATE_KEY_PATH', default='')
GITHUB_WEBHOOK_SECRET = env('GITHUB_WEBHOOK_SECRET', default='')
GITHUB_APP_INSTALL_URL = env('GITHUB_APP_INSTALL_URL', default='')
GITHUB_APP_TIMEOUT_SECONDS = env.int('GITHUB_APP_TIMEOUT_SECONDS', default=20)
GITHUB_APP_STATE_TTL_SECONDS = env.int('GITHUB_APP_STATE_TTL_SECONDS', default=900)
VEYRA_FRONTEND_URL = env('VEYRA_FRONTEND_URL', default='http://localhost:3000')
VEYRA_PUBLIC_API_URL = env('VEYRA_PUBLIC_API_URL', default='http://127.0.0.1:8000')
VEYRA_ALLOW_LOCAL_AGENT_RUNTIME = env.bool(
    'VEYRA_ALLOW_LOCAL_AGENT_RUNTIME', default=DEBUG
)
VEYRA_AGENT_CONNECTION_PROTOCOL_VERSION = env.int(
    'VEYRA_AGENT_CONNECTION_PROTOCOL_VERSION', default=1
)
VEYRA_AGENT_CONNECTION_TIMEOUT_SECONDS = env.int(
    'VEYRA_AGENT_CONNECTION_TIMEOUT_SECONDS', default=20
)
VEYRA_AGENT_RUNTIME_ONLINE_WINDOW_SECONDS = env.int(
    'VEYRA_AGENT_RUNTIME_ONLINE_WINDOW_SECONDS', default=35
)
VEYRA_CONTRACT_OWNER_WALLET_ADDRESS = env(
    'VEYRA_CONTRACT_OWNER_WALLET_ADDRESS', default=''
)
# For the current Arc Testnet deployment, the original deployer EOA remains
# the contract owner. The backend signs owner-only administration calls with
# this server-side secret. In production, move this signer into a KMS/HSM.
VEYRA_CONTRACT_OWNER_PRIVATE_KEY = env(
    'VEYRA_CONTRACT_OWNER_PRIVATE_KEY',
    default=env('DEPLOYER_PRIVATE_KEY', default=''),
)
VEYRA_CONTRACT_AUTHORISATION_FEE_LEVEL = env(
    'VEYRA_CONTRACT_AUTHORISATION_FEE_LEVEL', default='MEDIUM'
)
VEYRA_CONTRACT_AUTHORISATION_TIMEOUT_SECONDS = env.int(
    'VEYRA_CONTRACT_AUTHORISATION_TIMEOUT_SECONDS', default=180
)
VEYRA_CONTRACT_AUTHORISATION_POLL_INTERVAL_SECONDS = env.int(
    'VEYRA_CONTRACT_AUTHORISATION_POLL_INTERVAL_SECONDS', default=3
)
# The current Arc Testnet jobs use the deployer EOA as their authorised verifier.
# Production should move this key into a dedicated verifier KMS/HSM.
VEYRA_VERIFIER_PRIVATE_KEY = env(
    'VEYRA_VERIFIER_PRIVATE_KEY',
    default=VEYRA_CONTRACT_OWNER_PRIVATE_KEY,
)
VEYRA_JOB_RESERVATION_SECONDS = env.int('VEYRA_JOB_RESERVATION_SECONDS', default=90)
VEYRA_MATCHING_FAIRNESS_BAND = env.int('VEYRA_MATCHING_FAIRNESS_BAND', default=200)
VEYRA_JOB_LEASE_GRACE_SECONDS = env.int('VEYRA_JOB_LEASE_GRACE_SECONDS', default=120)
VEYRA_JOB_MAX_REPAIR_ATTEMPTS = env.int('VEYRA_JOB_MAX_REPAIR_ATTEMPTS', default=2)
VEYRA_REQUIRE_GITHUB_CHECKS = env.bool('VEYRA_REQUIRE_GITHUB_CHECKS', default=True)
VEYRA_VERIFIER_RESERVATION_SECONDS = env.int('VEYRA_VERIFIER_RESERVATION_SECONDS', default=90)
VEYRA_VERIFIER_LEASE_MINUTES = env.int('VEYRA_VERIFIER_LEASE_MINUTES', default=30)
VEYRA_SETTLEMENT_TIMEOUT_SECONDS = env.int('VEYRA_SETTLEMENT_TIMEOUT_SECONDS', default=180)
VEYRA_SETTLEMENT_POLL_INTERVAL_SECONDS = env.int(
    'VEYRA_SETTLEMENT_POLL_INTERVAL_SECONDS', default=3
)

WORKER_CIRCLE_WALLET_SET_NAME = env(
    'WORKER_CIRCLE_WALLET_SET_NAME',
    default='Veyra Worker Agents',
)

WORKER_ENGINE_EXECUTABLE = env('WORKER_ENGINE_EXECUTABLE', default='opencode')
WORKER_ENGINE_HEALTHCHECK_ARGS = env.list(
    'WORKER_ENGINE_HEALTHCHECK_ARGS',
    default=['--version'],
)
WORKER_ENGINE_TIMEOUT_SECONDS = env.int('WORKER_ENGINE_TIMEOUT_SECONDS', default=20)
WORKER_ENGINE_MODEL = env('WORKER_ENGINE_MODEL', default='zai-org/glm-5.2')
WORKER_DISCOVERY_MIN_REMAINING_SECONDS = env.int(
    'WORKER_DISCOVERY_MIN_REMAINING_SECONDS', default=900
)
WORKER_DISCOVERY_REQUIRE_SKILL_MATCH = env.bool(
    'WORKER_DISCOVERY_REQUIRE_SKILL_MATCH', default=True
)
WORKER_CLAIM_FEE_LEVEL = env('WORKER_CLAIM_FEE_LEVEL', default='MEDIUM')
WORKER_CLAIM_TIMEOUT_SECONDS = env.int('WORKER_CLAIM_TIMEOUT_SECONDS', default=180)
WORKER_CLAIM_POLL_INTERVAL_SECONDS = env.int(
    'WORKER_CLAIM_POLL_INTERVAL_SECONDS', default=3
)
WORKER_ARC_RECEIPT_TIMEOUT_SECONDS = env.int(
    'WORKER_ARC_RECEIPT_TIMEOUT_SECONDS', default=120
)
WORKER_EXECUTION_MIN_REMAINING_SECONDS = env.int(
    'WORKER_EXECUTION_MIN_REMAINING_SECONDS', default=900
)
WORKER_JOB_TEST_TIMEOUT_SECONDS = env.int(
    'WORKER_JOB_TEST_TIMEOUT_SECONDS', default=900
)
WORKER_SUBMISSION_MIN_REMAINING_SECONDS = env.int(
    'WORKER_SUBMISSION_MIN_REMAINING_SECONDS', default=120
)
WORKER_SUBMISSION_FEE_LEVEL = env('WORKER_SUBMISSION_FEE_LEVEL', default='MEDIUM')
WORKER_SUBMISSION_TIMEOUT_SECONDS = env.int(
    'WORKER_SUBMISSION_TIMEOUT_SECONDS', default=180
)
WORKER_SUBMISSION_POLL_INTERVAL_SECONDS = env.int(
    'WORKER_SUBMISSION_POLL_INTERVAL_SECONDS', default=3
)

VEYRA_RUNNER_PAIRING_TTL_SECONDS = env.int(
    'VEYRA_RUNNER_PAIRING_TTL_SECONDS', default=600
)
VEYRA_RUNNER_ONLINE_WINDOW_SECONDS = env.int(
    'VEYRA_RUNNER_ONLINE_WINDOW_SECONDS', default=35
)
VEYRA_RUNNER_SIGNATURE_MAX_SKEW_SECONDS = env.int(
    'VEYRA_RUNNER_SIGNATURE_MAX_SKEW_SECONDS', default=300
)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {'jsonish': {'format': '%(asctime)s %(levelname)s request_id=%(request_id)s %(name)s %(message)s'}},
    'filters': {'request_id': {'()': 'common.logging.RequestIdFilter'}},
    'handlers': {'console': {'class': 'logging.StreamHandler', 'formatter': 'jsonish', 'filters': ['request_id']}},
    'root': {'handlers': ['console'], 'level': env('LOG_LEVEL', default='INFO')},
}
