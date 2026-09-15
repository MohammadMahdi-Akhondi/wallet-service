from django.db.models import F

from wallets.models import Wallet


def create():
    return Wallet.objects.create()


def get_by_uuid(wallet_uuid):
    return Wallet.apis.get(uuid=wallet_uuid)


def get_locked_by_uuid(wallet_uuid):
    return Wallet.apis.select_for_update().get(uuid=wallet_uuid)


def get_locked_by_id(wallet_id):
    return Wallet.apis.select_for_update().get(id=wallet_id)


def increase_balance(wallet, amount):
    wallet.balance = F("balance") + amount
    wallet.save(update_fields=["balance", "updated_at"])
    return wallet


def decrease_balance(wallet, amount):
    wallet.balance = F("balance") - amount
    wallet.save(update_fields=["balance", "updated_at"])
    return wallet


def refresh(wallet, fields=None):
    wallet.refresh_from_db(fields=fields)
    return wallet
