import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from wallets.exceptions import WalletNotFound
from wallets.infrastructure.third_party import ThirdPartyTransferClient, TransferStatus
from wallets.models import Wallet, Withdrawal
from wallets.repositories import transaction_repository, wallet_repository, withdrawal_repository

logger = logging.getLogger(__name__)

EXECUTABLE_STATUSES = (Withdrawal.Status.PENDING, Withdrawal.Status.RETRYING)


def schedule_withdrawal(wallet_uuid, amount, execute_at):
    amount = int(amount)
    if amount <= 0:
        raise ValueError("Withdrawal amount must be positive.")

    if execute_at <= timezone.now():
        raise ValueError("Execution timestamp must be in the future.")

    try:
        wallet = wallet_repository.get_by_uuid(wallet_uuid)

    except Wallet.DoesNotExist as exc:
        raise WalletNotFound("Wallet does not exist.") from exc

    withdrawal = withdrawal_repository.create(wallet, amount, execute_at)
    transaction.on_commit(lambda: _enqueue_withdrawal_execution(withdrawal))
    return withdrawal


def claim_due_withdrawal_ids(limit=100):
    now = timezone.now()

    with transaction.atomic():
        withdrawals = withdrawal_repository.list_locked_due(now, EXECUTABLE_STATUSES, limit)
        return [withdrawal.id for withdrawal in withdrawals]


def recover_stale_processing_withdrawals(timeout_seconds=300):
    cutoff = timezone.now() - timedelta(seconds=timeout_seconds)
    recovered_ids = []

    with transaction.atomic():
        for withdrawal in withdrawal_repository.iter_locked_stale_processing(cutoff):
            if _reservation_exists(withdrawal):
                withdrawal_repository.mark_unknown(
                    withdrawal,
                    "Worker stopped after funds were reserved; external transfer outcome is unknown.",
                    timezone.now(),
                )
                logger.error(
                    "Marked stale withdrawal as unknown after wallet funds had been reserved.",
                    extra={"withdrawal_id": withdrawal.id, "wallet_id": withdrawal.wallet_id},
                )
                continue

            withdrawal_repository.mark_retrying(
                withdrawal,
                "Recovered stale processing withdrawal before funds were reserved.",
            )
            recovered_ids.append(withdrawal.id)

    return recovered_ids


def execute_withdrawal(withdrawal_id, client=None):
    withdrawal = _claim_withdrawal(withdrawal_id)
    if withdrawal is None:
        return withdrawal_repository.get_by_id(withdrawal_id)

    if not _reserve_funds(withdrawal.id):
        return withdrawal_repository.get_by_id(withdrawal_id)

    withdrawal_repository.refresh(withdrawal)
    client = client or ThirdPartyTransferClient()
    logger.info(
        "Calling third-party transfer service.",
        extra={
            "withdrawal_id": withdrawal.id,
            "wallet_id": withdrawal.wallet_id,
            "wallet_uuid": str(withdrawal.wallet.uuid),
            "amount": withdrawal.amount,
        },
    )
    result = client.transfer(
        wallet_uuid=withdrawal.wallet.uuid,
        amount=withdrawal.amount,
        withdrawal_id=withdrawal.id,
    )
    return _finalize_external_result(withdrawal.id, result)


def _claim_withdrawal(withdrawal_id):
    with transaction.atomic():
        withdrawal = withdrawal_repository.first_locked_with_wallet(withdrawal_id)
        if not withdrawal or withdrawal.status not in EXECUTABLE_STATUSES:
            return None

        if withdrawal.execute_at > timezone.now():
            return None

        withdrawal_repository.mark_processing(withdrawal, timezone.now())

    return withdrawal_repository.get_with_wallet_by_id(withdrawal_id)


def _enqueue_withdrawal_execution(withdrawal):
    from wallets.tasks import execute_withdrawal

    execute_withdrawal.apply_async(args=[withdrawal.id], eta=withdrawal.execute_at)


def _reservation_exists(withdrawal):
    return transaction_repository.successful_reservation_exists(withdrawal)


def _reserve_funds(withdrawal_id):
    with transaction.atomic():
        withdrawal = withdrawal_repository.get_locked_with_wallet_by_id(withdrawal_id)
        wallet = wallet_repository.get_locked_by_id(withdrawal.wallet_id)

        if withdrawal.status != Withdrawal.Status.PROCESSING:
            return False

        if _reservation_exists(withdrawal):
            return True

        if wallet.balance < withdrawal.amount:
            transaction_repository.create_failed_reservation(wallet, withdrawal, "insufficient_funds")
            withdrawal_repository.mark_failed(withdrawal, "Insufficient funds.", timezone.now())
            return False

        wallet_repository.decrease_balance(wallet, withdrawal.amount)
        transaction_repository.create_successful_reservation(wallet, withdrawal)
        return True


def _finalize_external_result(withdrawal_id, result):
    if result.status == TransferStatus.SUCCESS:
        logger.info(
            "Third-party transfer completed successfully.",
            extra={
                "withdrawal_id": withdrawal_id,
                "http_status": result.http_status,
                "response_payload": result.response_payload,
            },
        )
        return _mark_withdrawal_success(withdrawal_id)

    if result.status == TransferStatus.FAILED:
        logger.warning(
            "Third-party transfer failed explicitly; refunding reserved wallet funds.",
            extra={
                "withdrawal_id": withdrawal_id,
                "http_status": result.http_status,
                "response_payload": result.response_payload,
                "error": result.error_message,
            },
        )
        return _refund_and_fail(withdrawal_id, result.error_message or "Third-party transfer failed.")

    logger.error(
        "Third-party transfer outcome is unknown; leaving reserved funds unreconciled.",
        extra={
            "withdrawal_id": withdrawal_id,
            "http_status": result.http_status,
            "response_payload": result.response_payload,
            "error": result.error_message,
        },
    )
    return _mark_withdrawal_unknown(withdrawal_id, result.error_message or "External transfer outcome is unknown.")


def _mark_withdrawal_success(withdrawal_id):
    with transaction.atomic():
        withdrawal = withdrawal_repository.get_locked_by_id(withdrawal_id)
        if withdrawal.status != Withdrawal.Status.SUCCESS:
            withdrawal_repository.mark_success(withdrawal, timezone.now())
        transaction_repository.create_capture_if_missing(withdrawal)
    return withdrawal_repository.get_by_id(withdrawal_id)


def _refund_and_fail(withdrawal_id, reason):
    with transaction.atomic():
        withdrawal = withdrawal_repository.get_locked_by_id(withdrawal_id)
        wallet = wallet_repository.get_locked_by_id(withdrawal.wallet_id)
        if not transaction_repository.successful_refund_exists(withdrawal):
            _, refund_created = transaction_repository.create_successful_refund_if_missing(wallet, withdrawal)
            if refund_created:
                wallet_repository.increase_balance(wallet, withdrawal.amount)

        withdrawal_repository.mark_failed(withdrawal, reason, timezone.now())
    return withdrawal_repository.get_by_id(withdrawal_id)


def _mark_withdrawal_unknown(withdrawal_id, reason):
    with transaction.atomic():
        withdrawal = withdrawal_repository.get_locked_by_id(withdrawal_id)
        withdrawal_repository.mark_unknown(withdrawal, reason, timezone.now())
    return withdrawal_repository.get_by_id(withdrawal_id)
