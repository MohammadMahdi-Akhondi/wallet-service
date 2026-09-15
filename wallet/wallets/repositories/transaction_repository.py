from wallets.models import Transaction


def create_deposit(wallet, amount):
    return Transaction.objects.create(
        wallet=wallet,
        type=Transaction.Type.DEPOSIT,
        amount=amount,
        status=Transaction.Status.SUCCESS,
    )


def successful_reservation_exists(withdrawal):
    return Transaction.apis.filter(
        withdrawal_id=withdrawal.id,
        type=Transaction.Type.WITHDRAWAL_RESERVATION,
        status=Transaction.Status.SUCCESS,
    ).exists()


def create_failed_reservation(wallet, withdrawal, reason):
    return Transaction.apis.create(
        wallet=wallet,
        withdrawal=withdrawal,
        type=Transaction.Type.WITHDRAWAL_RESERVATION,
        amount=-withdrawal.amount,
        status=Transaction.Status.FAILED,
        metadata={"reason": reason},
    )


def create_successful_reservation(wallet, withdrawal):
    return Transaction.apis.create(
        wallet=wallet,
        withdrawal=withdrawal,
        type=Transaction.Type.WITHDRAWAL_RESERVATION,
        amount=-withdrawal.amount,
        status=Transaction.Status.SUCCESS,
        metadata={"withdrawal_id": withdrawal.id},
    )


def create_capture_if_missing(withdrawal):
    capture, _ = Transaction.apis.get_or_create(
        wallet_id=withdrawal.wallet_id,
        withdrawal=withdrawal,
        type=Transaction.Type.WITHDRAWAL_CAPTURE,
        defaults={
            "amount": -withdrawal.amount,
            "status": Transaction.Status.SUCCESS,
            "metadata": {"withdrawal_id": withdrawal.id},
        },
    )
    return capture


def successful_refund_exists(withdrawal):
    return Transaction.apis.filter(
        withdrawal_id=withdrawal.id,
        type=Transaction.Type.WITHDRAWAL_REFUND,
        status=Transaction.Status.SUCCESS,
    ).exists()


def create_successful_refund_if_missing(wallet, withdrawal):
    return Transaction.apis.get_or_create(
        wallet_id=wallet.id,
        withdrawal=withdrawal,
        type=Transaction.Type.WITHDRAWAL_REFUND,
        defaults={
            "amount": withdrawal.amount,
            "status": Transaction.Status.SUCCESS,
            "metadata": {"withdrawal_id": withdrawal.id},
        },
    )
