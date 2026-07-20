from rest_framework import serializers
from accounts.models import ClientProfile, ExternalIdentity

class SocialDeviceSerializer(serializers.Serializer):
    device_id = serializers.CharField(min_length=8, max_length=255)

class EmailRequestSerializer(serializers.Serializer):
    device_id = serializers.CharField(min_length=8, max_length=255)
    email = serializers.EmailField()

class CircleExchangeSerializer(serializers.Serializer):
    user_token = serializers.CharField(min_length=20)
    circle_user_id = serializers.CharField(max_length=255, required=False, allow_blank=True)
    auth_method = serializers.ChoiceField(choices=ExternalIdentity.Method.choices)
    email = serializers.EmailField(required=False, allow_blank=True)
    display_name = serializers.CharField(max_length=120, required=False, allow_blank=True)

class ClientOnboardingSerializer(serializers.Serializer):
    organisation_name = serializers.CharField(max_length=160, required=False, allow_blank=True)
    notification_email = serializers.EmailField(required=False, allow_blank=True)
    timezone = serializers.CharField(max_length=64, required=False, default='UTC')
    github_username = serializers.CharField(max_length=80, required=False, allow_blank=True)

class ClientProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClientProfile
        fields = ['organisation_name', 'notification_email', 'timezone', 'github_username']
