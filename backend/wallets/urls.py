from django.urls import path
from wallets.views import WalletBalanceView, WalletDetailView, WalletInitializeView, WalletSyncView

urlpatterns = [
    path('wallet/', WalletDetailView.as_view()),
    path('wallet/initialize/', WalletInitializeView.as_view()),
    path('wallet/sync/', WalletSyncView.as_view()),
    path('wallet/balance/', WalletBalanceView.as_view()),
]
