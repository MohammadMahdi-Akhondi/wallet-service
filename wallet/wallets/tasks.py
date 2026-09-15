from celery import shared_task
from django.conf import settings

from wallets.services.withdrawal_service import claim_due_withdrawal_ids
from wallets.services.withdrawal_service import execute_withdrawal as execute_withdrawal_service
from wallets.services.withdrawal_service import (
    recover_stale_processing_withdrawals as recover_stale_processing_withdrawals_service,
)


@shared_task(name="wallets.tasks.enqueue_due_withdrawals")
def enqueue_due_withdrawals():
    withdrawal_ids = claim_due_withdrawal_ids(limit=settings.WITHDRAWAL_SCAN_LIMIT)
    for withdrawal_id in withdrawal_ids:
        execute_withdrawal.delay(withdrawal_id)

    return withdrawal_ids


@shared_task(name="wallets.tasks.execute_withdrawal")
def execute_withdrawal(withdrawal_id):
    withdrawal = execute_withdrawal_service(withdrawal_id)
    return {"withdrawal_id": withdrawal.id, "status": withdrawal.status}


@shared_task(name="wallets.tasks.recover_stale_processing_withdrawals")
def recover_stale_processing_withdrawals():
    return recover_stale_processing_withdrawals_service(timeout_seconds=settings.WITHDRAWAL_STALE_PROCESSING_SECONDS)
