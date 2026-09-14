from django.utils import timezone
from rest_framework import serializers

from wallets.models import Wallet, Withdrawal


class WalletSerializer(serializers.ModelSerializer):
    class Meta:
        model = Wallet
        fields = ("uuid", "balance", "created_at", "updated_at")
        read_only_fields = ("uuid", "balance", "created_at", "updated_at")


class DepositSerializer(serializers.Serializer):
    amount = serializers.IntegerField(min_value=1)


class WithdrawalScheduleSerializer(serializers.Serializer):
    amount = serializers.IntegerField(min_value=1)
    execute_at = serializers.DateTimeField()

    def validate_execute_at(self, value):
        if value <= timezone.now():
            raise serializers.ValidationError("Execution timestamp must be in the future.")
        return value


class WithdrawalSerializer(serializers.ModelSerializer):
    wallet_uuid = serializers.UUIDField(source="wallet.uuid", read_only=True)

    class Meta:
        model = Withdrawal
        fields = (
            "id",
            "wallet_uuid",
            "amount",
            "execute_at",
            "status",
            "failure_reason",
            "attempt_count",
            "processed_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields
