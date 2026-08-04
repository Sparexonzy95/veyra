from rest_framework import serializers

class WalletInitializeSerializer(serializers.Serializer):
    circle_user_id = serializers.CharField(max_length=255, required=False, allow_blank=True)
    auth_method = serializers.ChoiceField(choices=['GOOGLE', 'EMAIL'], required=False, default='GOOGLE')
    email = serializers.EmailField(required=False, allow_blank=True)
    display_name = serializers.CharField(max_length=120, required=False, allow_blank=True)

class CircleResultSerializer(serializers.Serializer):
    circle_transaction_id = serializers.CharField(max_length=128)
