from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("workers", "0017_execution_layer_state_and_matching_retry"),
    ]

    operations = [
        migrations.AddField(
            model_name="workeragent",
            name="contract_authorisation_nonce",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="workeragent",
            name="contract_authorisation_raw_transaction",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="workerjobassignment",
            name="failure_history",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="workerjobassignment",
            name="settlement_nonce",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="workerjobassignment",
            name="settlement_raw_transaction",
            field=models.TextField(blank=True),
        ),
    ]
