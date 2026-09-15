from typing import ClassVar

from common.models import BaseModel
from django.db import models
from django.db.models import Q


class Transaction(BaseModel):
    class Type(models.TextChoices):
        DEPOSIT = "deposit", "Deposit"
        WITHDRAWAL_RESERVATION = "withdrawal_reservation", "Withdrawal reservation"
        WITHDRAWAL_CAPTURE = "withdrawal_capture", "Withdrawal capture"
        WITHDRAWAL_REFUND = "withdrawal_refund", "Withdrawal refund"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"

    wallet = models.ForeignKey("wallets.Wallet", related_name="transactions", on_delete=models.PROTECT)
    withdrawal = models.ForeignKey(
        "wallets.Withdrawal", related_name="transactions", null=True, blank=True, on_delete=models.PROTECT
    )
    type = models.CharField(max_length=32, choices=Type.choices)
    amount = models.BigIntegerField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.SUCCESS)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["wallet", "created_at"]),
            models.Index(fields=["withdrawal", "type"]),
            models.Index(fields=["type", "status"]),
            models.Index(fields=["created_at"]),
        ]
        constraints: ClassVar[list[models.CheckConstraint | models.UniqueConstraint]] = [
            models.CheckConstraint(check=~Q(amount=0), name="wallet_transaction_amount_not_zero"),
            models.UniqueConstraint(
                fields=["withdrawal", "type"],
                condition=Q(withdrawal__isnull=False),
                name="unique_transaction_withdrawal_type",
            ),
        ]
