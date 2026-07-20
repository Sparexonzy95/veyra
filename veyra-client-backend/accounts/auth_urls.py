from django.urls import path
from accounts.views import CircleEmailRequestView, CircleExchangeView, CircleSocialDeviceView, LogoutView, MeView

urlpatterns = [
    path('circle/social/device/', CircleSocialDeviceView.as_view()),
    path('circle/email/request/', CircleEmailRequestView.as_view()),
    path('circle/exchange/', CircleExchangeView.as_view()),
    path('me/', MeView.as_view()),
    path('logout/', LogoutView.as_view()),
]
