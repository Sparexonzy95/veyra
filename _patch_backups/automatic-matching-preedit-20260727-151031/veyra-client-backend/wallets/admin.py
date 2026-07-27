from django.contrib import admin
from wallets.models import CircleTransaction, WalletAccount
admin.site.register([WalletAccount, CircleTransaction])
