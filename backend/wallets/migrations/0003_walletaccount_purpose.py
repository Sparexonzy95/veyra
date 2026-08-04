from django.db import migrations, models


def classify_existing_wallets(apps, schema_editor):
    WalletAccount = apps.get_model('wallets', 'WalletAccount')
    UserCapability = apps.get_model('accounts', 'UserCapability')

    client_user_ids = set(
        UserCapability.objects.filter(
            code='CLIENT',
            revoked_at__isnull=True,
        ).values_list('user_id', flat=True)
    )
    WalletAccount.objects.exclude(user_id__in=client_user_ids).update(
        purpose='IDENTITY_ONLY',
    )


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0002_pendingcircleauth_profile_data'),
        ('wallets', '0002_transaction_receipt_tracking'),
    ]

    operations = [
        migrations.AddField(
            model_name='walletaccount',
            name='purpose',
            field=models.CharField(
                choices=[
                    ('IDENTITY_ONLY', 'Sign-in identity only'),
                    ('CLIENT_ESCROW', 'Client escrow wallet'),
                ],
                default='CLIENT_ESCROW',
                max_length=24,
            ),
        ),
        migrations.RunPython(classify_existing_wallets, migrations.RunPython.noop),
    ]
