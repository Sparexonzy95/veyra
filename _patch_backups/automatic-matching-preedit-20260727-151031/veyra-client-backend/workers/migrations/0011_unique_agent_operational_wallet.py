from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('workers', '0010_provision_veyra_hosted_runtimes'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='workeragent',
            constraint=models.UniqueConstraint(
                condition=~models.Q(worker_wallet_address=''),
                fields=('worker_wallet_address',),
                name='uniq_worker_operational_wallet_address',
            ),
        ),
    ]
