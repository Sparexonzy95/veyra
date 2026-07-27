from django.contrib import admin
from jobs.models import ArcEvent, JobDraft, JobFundingSnapshot, Notification, VeyraJob
admin.site.register([JobDraft, JobFundingSnapshot, VeyraJob, ArcEvent, Notification])
