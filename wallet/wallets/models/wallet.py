import uuid
from typing import ClassVar

from common.models import BaseModel
from django.db import models
from django.db.models import Q


class Wallet(BaseModel):
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True)
    balance = models.BigIntegerField(default=0)

    def deposit(self, amount: int):
        from wallets.services.wallet_service import deposit

        return deposit(self.uuid, amount)

    class Meta:
        constraints: ClassVar[list[models.CheckConstraint]] = [
            models.CheckConstraint(check=Q(balance__gte=0), name="wallet_balance_non_negative"),
        ]
