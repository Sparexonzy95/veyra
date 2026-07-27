import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('jobs', '0001_initial'),
        ('wallets', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='circletransaction',
            name='block_number',
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='circletransaction',
            name='draft',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='transactions', to='jobs.jobdraft'),
        ),
        migrations.AddField(
            model_name='circletransaction',
            name='event_payload',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='circletransaction',
            name='gas_used',
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='circletransaction',
            name='job',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='transactions', to='jobs.veyrajob'),
        ),
        migrations.AddField(
            model_name='circletransaction',
            name='last_checked_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='circletransaction',
            name='receipt_status',
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='circletransaction',
            name='sync_attempts',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AlterField(
            model_name='circletransaction',
            name='status',
            field=models.CharField(choices=[('CREATED', 'Created'), ('CHALLENGE_READY', 'Challenge ready'), ('USER_APPROVAL_PENDING', 'User approval pending'), ('SUBMITTED', 'Submitted'), ('PENDING_ONCHAIN', 'Pending onchain'), ('CONFIRMED', 'Confirmed'), ('DENIED', 'Denied'), ('FAILED', 'Failed'), ('EXPIRED', 'Expired'), ('EVENT_MISMATCH', 'Event mismatch')], default='CREATED', max_length=32),
        ),
        migrations.AddIndex(
            model_name='circletransaction',
            index=models.Index(fields=['draft', 'purpose', 'status'], name='wallets_cir_draft_i_9c4781_idx'),
        ),
    ]
