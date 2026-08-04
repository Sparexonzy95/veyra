from drf_spectacular.utils import OpenApiTypes, extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

class CircleWebhookView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
    def post(self, request):
        # Deliberately disabled until Circle's official webhook signature verifier
        # is configured. Polling/reconciliation commands remain the safe fallback.
        return Response({'detail': 'Circle webhook verification is not configured.'}, status=501)
