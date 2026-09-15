from typing import ClassVar

from common.models import BaseModel
from django.db import models
from django.db.models import Q


class Withdrawal(BaseModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"
        UNKNOWN = "unknown", "Unknown"
        RETRYING = "retrying", "Retrying"

    wallet = models.ForeignKey("wallets.Wallet", related_name="withdrawals", on_delete=models.PROTECT)
    amount = models.BigIntegerField()
    execute_at = models.DateTimeField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    failure_reason = models.TextField(blank=True)
    attempt_count = models.PositiveIntegerField(default=0)
    locked_at = models.DateTimeField(null=True, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["status", "execute_at"]),
            models.Index(fields=["wallet", "status"]),
            models.Index(fields=["locked_at"]),
        ]
        constraints: ClassVar[list[models.CheckConstraint]] = [
            models.CheckConstraint(check=Q(amount__gt=0), name="withdrawal_amount_positive"),
        ]
