from django.urls import path

from .views import (
    CreateDepositView,
    CreateWalletView,
    RetrieveWalletView,
    ScheduleWithdrawalView,
)

urlpatterns = [
    path("", CreateWalletView.as_view()),
    path("<uuid:uuid>/", RetrieveWalletView.as_view()),
    path("<uuid:uuid>/deposit", CreateDepositView.as_view()),
    path("<uuid:uuid>/withdrawal", ScheduleWithdrawalView.as_view()),
]
