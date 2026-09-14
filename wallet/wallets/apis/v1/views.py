from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.generics import CreateAPIView, RetrieveAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from wallets.exceptions import WalletNotFound
from wallets.models import Wallet
from wallets.services.wallet_service import deposit
from wallets.services.withdrawal_service import schedule_withdrawal

from .serializers import (
    DepositSerializer,
    WalletSerializer,
    WithdrawalScheduleSerializer,
    WithdrawalSerializer,
)


class CreateWalletView(CreateAPIView):
    serializer_class = WalletSerializer


class RetrieveWalletView(RetrieveAPIView):
    serializer_class = WalletSerializer
    queryset = Wallet.apis.all()
    lookup_field = "uuid"


class CreateDepositView(APIView):
    @extend_schema(
        request=DepositSerializer,
        responses={
            status.HTTP_200_OK: WalletSerializer,
            status.HTTP_404_NOT_FOUND: OpenApiResponse(description="Wallet not found."),
        },
    )
    def post(self, request, *args, **kwargs):
        serializer = DepositSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            wallet = deposit(kwargs["uuid"], serializer.validated_data["amount"])

        except WalletNotFound:
            return Response({"detail": "Wallet not found."}, status=status.HTTP_404_NOT_FOUND)

        return Response(WalletSerializer(wallet).data, status=status.HTTP_200_OK)


class ScheduleWithdrawalView(APIView):
    @extend_schema(
        request=WithdrawalScheduleSerializer,
        responses={
            status.HTTP_201_CREATED: WithdrawalSerializer,
            status.HTTP_404_NOT_FOUND: OpenApiResponse(description="Wallet not found."),
        },
    )
    def post(self, request, *args, **kwargs):
        serializer = WithdrawalScheduleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            withdrawal = schedule_withdrawal(
                kwargs["uuid"],
                serializer.validated_data["amount"],
                serializer.validated_data["execute_at"],
            )

        except WalletNotFound:
            return Response({"detail": "Wallet not found."}, status=status.HTTP_404_NOT_FOUND)

        return Response(WithdrawalSerializer(withdrawal).data, status=status.HTTP_201_CREATED)
