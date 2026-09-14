from django.db import transaction

from wallets.exceptions import WalletNotFound
from wallets.models import Wallet
from wallets.repositories import transaction_repository, wallet_repository


def create_wallet():
    return wallet_repository.create()


def get_locked_wallet(wallet_uuid):
    try:
        return wallet_repository.get_locked_by_uuid(wallet_uuid)

    except Wallet.DoesNotExist as exc:
        raise WalletNotFound("Wallet does not exist.") from exc


def deposit(wallet_uuid, amount):
    amount = int(amount)
    if amount <= 0:
        raise ValueError("Deposit amount must be positive.")

    with transaction.atomic():
        wallet = get_locked_wallet(wallet_uuid)
        wallet_repository.increase_balance(wallet, amount)
        transaction_repository.create_deposit(wallet, amount)

    return wallet_repository.refresh(wallet, fields=["balance", "updated_at"])
