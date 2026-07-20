import uuid
from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.utils import timezone
from common.models import TimeStampedModel

class UserManager(BaseUserManager):
    def create_user(self, handle=None, **extra_fields):
        handle = handle or f'user_{uuid.uuid4().hex[:18]}'
        user = self.model(handle=handle, **extra_fields)
        user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, handle, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        user = self.model(handle=handle, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

class User(AbstractBaseUser, PermissionsMixin):
    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Active'
        SUSPENDED = 'SUSPENDED', 'Suspended'
        CLOSED = 'CLOSED', 'Closed'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    handle = models.CharField(max_length=64, unique=True)
    email = models.EmailField(blank=True)
    display_name = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    date_joined = models.DateTimeField(default=timezone.now)
    last_login_at = models.DateTimeField(null=True, blank=True)

    objects = UserManager()
    USERNAME_FIELD = 'handle'

    def __str__(self):
        return self.display_name or self.handle

class ExternalIdentity(TimeStampedModel):
    class Provider(models.TextChoices):
        CIRCLE = 'CIRCLE', 'Circle'

    class Method(models.TextChoices):
        GOOGLE = 'GOOGLE', 'Google'
        EMAIL = 'EMAIL', 'Email'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, related_name='external_identities', on_delete=models.CASCADE)
    provider = models.CharField(max_length=20, choices=Provider.choices)
    provider_user_id = models.CharField(max_length=255)
    method = models.CharField(max_length=20, choices=Method.choices)
    verified_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['provider', 'provider_user_id'], name='uniq_external_provider_user'),
        ]

class UserCapability(models.Model):
    class Code(models.TextChoices):
        CLIENT = 'CLIENT', 'Client'
        AGENT_OWNER = 'AGENT_OWNER', 'Agent owner'
        ADMIN = 'ADMIN', 'Admin'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, related_name='capabilities', on_delete=models.CASCADE)
    code = models.CharField(max_length=32, choices=Code.choices)
    granted_at = models.DateTimeField(default=timezone.now)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'code'], name='uniq_user_capability')]

class ClientProfile(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(User, related_name='client_profile', on_delete=models.CASCADE)
    organisation_name = models.CharField(max_length=160, blank=True)
    notification_email = models.EmailField(blank=True)
    timezone = models.CharField(max_length=64, default='UTC')
    github_username = models.CharField(max_length=80, blank=True)

class VeyraSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, related_name='veyra_sessions', on_delete=models.CASCADE)
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(default=timezone.now)
    user_agent_hash = models.CharField(max_length=64, blank=True)

    class Meta:
        indexes = [models.Index(fields=['token_hash', 'expires_at'])]

class PendingCircleAuth(models.Model):
    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Active'
        CONSUMED = 'CONSUMED', 'Consumed'
        EXPIRED = 'EXPIRED', 'Expired'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    onboarding_token_hash = models.CharField(max_length=64, unique=True)
    circle_user_token_hash = models.CharField(max_length=64)
    circle_user_id = models.CharField(max_length=255, blank=True)
    auth_method = models.CharField(max_length=20, choices=ExternalIdentity.Method.choices)
    email_hint = models.EmailField(blank=True)
    display_name_hint = models.CharField(max_length=120, blank=True)
    requested_capability = models.CharField(max_length=32, blank=True)
    profile_data = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=['onboarding_token_hash', 'expires_at'])]
