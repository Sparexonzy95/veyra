import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0002_pendingcircleauth_profile_data'),
    ]

    operations = [
        migrations.CreateModel(
            name='AgentOwnerProfile',
            fields=[
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('notification_email', models.EmailField(blank=True, max_length=254)),
                ('timezone', models.CharField(default='UTC', max_length=64)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='agent_owner_profile', to=settings.AUTH_USER_MODEL)),
            ],
            options={'abstract': False},
        ),
    ]
