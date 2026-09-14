from django.db.models import F

from wallets.models import Withdrawal


def create(wallet, amount, execute_at):
    return Withdrawal.objects.create(wallet=wallet, amount=amount, execute_at=execute_at)


def get_by_id(withdrawal_id):
    return Withdrawal.apis.get(id=withdrawal_id)


def get_with_wallet_by_id(withdrawal_id):
    return Withdrawal.apis.select_related("wallet").get(id=withdrawal_id)


def get_locked_by_id(withdrawal_id):
    return Withdrawal.apis.filter(id=withdrawal_id).select_for_update().get()


def get_locked_with_wallet_by_id(withdrawal_id):
    return Withdrawal.apis.select_related("wallet").filter(id=withdrawal_id).select_for_update(of=("self",)).get()


def first_locked_with_wallet(withdrawal_id):
    return Withdrawal.apis.select_related("wallet").filter(id=withdrawal_id).select_for_update(of=("self",)).first()


def list_locked_due(now, statuses, limit):
    queryset = Withdrawal.apis.filter(status__in=statuses, execute_at__lte=now).order_by("execute_at", "id")
    return list(queryset.select_for_update(skip_locked=True)[:limit])


def iter_locked_stale_processing(cutoff):
    return (
        Withdrawal.apis.filter(status=Withdrawal.Status.PROCESSING, locked_at__lt=cutoff)
        .order_by("locked_at")
        .select_for_update()
    )


def mark_processing(withdrawal, locked_at):
    withdrawal.status = Withdrawal.Status.PROCESSING
    withdrawal.locked_at = locked_at
    withdrawal.failure_reason = ""
    withdrawal.attempt_count = F("attempt_count") + 1
    withdrawal.save(update_fields=["status", "locked_at", "failure_reason", "attempt_count", "updated_at"])
    return withdrawal


def mark_retrying(withdrawal, reason):
    withdrawal.status = Withdrawal.Status.RETRYING
    withdrawal.failure_reason = reason
    withdrawal.save(update_fields=["status", "failure_reason", "updated_at"])
    return withdrawal


def mark_failed(withdrawal, reason, processed_at):
    withdrawal.status = Withdrawal.Status.FAILED
    withdrawal.failure_reason = reason
    withdrawal.processed_at = processed_at
    withdrawal.save(update_fields=["status", "failure_reason", "processed_at", "updated_at"])
    return withdrawal


def mark_success(withdrawal, processed_at):
    withdrawal.status = Withdrawal.Status.SUCCESS
    withdrawal.failure_reason = ""
    withdrawal.processed_at = processed_at
    withdrawal.save(update_fields=["status", "failure_reason", "processed_at", "updated_at"])
    return withdrawal


def mark_unknown(withdrawal, reason, processed_at):
    withdrawal.status = Withdrawal.Status.UNKNOWN
    withdrawal.failure_reason = reason
    withdrawal.processed_at = processed_at
    withdrawal.save(update_fields=["status", "failure_reason", "processed_at", "updated_at"])
    return withdrawal


def refresh(withdrawal):
    withdrawal.refresh_from_db()
    return withdrawal
