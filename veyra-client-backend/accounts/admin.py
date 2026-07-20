from django.contrib import admin
from accounts.models import ClientProfile, ExternalIdentity, PendingCircleAuth, User, UserCapability, VeyraSession

admin.site.register([User, ExternalIdentity, UserCapability, ClientProfile, VeyraSession, PendingCircleAuth])
