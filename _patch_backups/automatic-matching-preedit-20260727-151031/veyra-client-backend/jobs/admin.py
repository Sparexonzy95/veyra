from django.contrib import admin
from jobs.models import ArcEvent, GitHubAppInstallation, GitHubRepositoryAccess, JobDraft, JobFundingSnapshot, Notification, VeyraJob
admin.site.register([JobDraft, JobFundingSnapshot, VeyraJob, ArcEvent, Notification, GitHubAppInstallation, GitHubRepositoryAccess])
