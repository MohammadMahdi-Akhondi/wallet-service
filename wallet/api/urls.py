from django.urls import include, path

urlpatterns = [
    path("v1/wallets/", include(("wallets.apis.v1.urls", "wallet"))),
]
