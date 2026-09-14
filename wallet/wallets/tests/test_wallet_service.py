from datetime import timedelta
from unittest.mock import patch

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from wallets.infrastructure.third_party import TransferResult, TransferStatus
from wallets.models import Transaction, Wallet, Withdrawal
from wallets.repositories import transaction_repository
from wallets.services.withdrawal_service import (
    claim_due_withdrawal_ids,
    execute_withdrawal,
    recover_stale_processing_withdrawals,
    schedule_withdrawal,
)


class FakeTransferClient:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def transfer(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


class WalletApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_create_wallet(self):
        response = self.client.post("/wallets/", data={}, format="json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(Wallet.objects.count(), 1)
        self.assertEqual(response.data["balance"], 0)

    def test_deposit_increases_balance_and_writes_transaction(self):
        wallet = Wallet.objects.create()

        response = self.client.post(f"/wallets/{wallet.uuid}/deposit", data={"amount": 250}, format="json")

        self.assertEqual(response.status_code, 200)
        wallet.refresh_from_db()
        self.assertEqual(wallet.balance, 250)
        self.assertEqual(
            Transaction.objects.get(wallet=wallet, type=Transaction.Type.DEPOSIT).amount,
            250,
        )

    def test_deposit_rejects_non_positive_amount(self):
        wallet = Wallet.objects.create()

        response = self.client.post(f"/wallets/{wallet.uuid}/deposit", data={"amount": 0}, format="json")

        self.assertEqual(response.status_code, 400)
        wallet.refresh_from_db()
        self.assertEqual(wallet.balance, 0)

    def test_schedule_withdrawal_creates_only_pending_withdrawal(self):
        wallet = Wallet.objects.create()
        execute_at = timezone.now() + timedelta(hours=1)

        response = self.client.post(
            f"/wallets/{wallet.uuid}/withdraw",
            data={"amount": 500, "execute_at": execute_at.isoformat()},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        withdrawal = Withdrawal.objects.get(wallet=wallet)
        self.assertEqual(withdrawal.status, Withdrawal.Status.PENDING)
        self.assertEqual(withdrawal.amount, 500)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_schedule_withdrawal_rejects_past_execute_at(self):
        wallet = Wallet.objects.create()
        execute_at = timezone.now() - timedelta(minutes=1)

        response = self.client.post(
            f"/wallets/{wallet.uuid}/withdraw",
            data={"amount": 500, "execute_at": execute_at.isoformat()},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Withdrawal.objects.count(), 0)


class WalletServiceTests(TestCase):
    def test_schedule_withdrawal_enqueues_eta_task_after_commit(self):
        wallet = Wallet.objects.create(balance=0)
        execute_at = timezone.now() + timedelta(minutes=5)

        with patch("wallets.tasks.execute_withdrawal.apply_async") as apply_async:
            with self.captureOnCommitCallbacks(execute=True):
                withdrawal = schedule_withdrawal(wallet.uuid, 1000, execute_at)

        apply_async.assert_called_once_with(args=[withdrawal.id], eta=execute_at)

    def test_schedule_withdrawal_does_not_check_balance(self):
        wallet = Wallet.objects.create(balance=0)

        withdrawal = schedule_withdrawal(wallet.uuid, 1000, timezone.now() + timedelta(minutes=5))

        self.assertEqual(withdrawal.status, Withdrawal.Status.PENDING)
        self.assertEqual(withdrawal.amount, 1000)

    def test_execute_withdrawal_before_execute_at_does_not_process(self):
        wallet = Wallet.objects.create(balance=500)
        withdrawal = Withdrawal.objects.create(
            wallet=wallet,
            amount=200,
            execute_at=timezone.now() + timedelta(minutes=1),
        )
        client = FakeTransferClient(TransferResult(status=TransferStatus.SUCCESS))

        result = execute_withdrawal(withdrawal.id, client=client)

        wallet.refresh_from_db()
        self.assertEqual(result.status, Withdrawal.Status.PENDING)
        self.assertEqual(wallet.balance, 500)
        self.assertEqual(client.calls, [])

    def test_withdrawal_transaction_type_is_unique(self):
        wallet = Wallet.objects.create(balance=500)
        withdrawal = Withdrawal.objects.create(
            wallet=wallet,
            amount=200,
            execute_at=timezone.now() - timedelta(minutes=1),
        )
        Transaction.objects.create(
            wallet=wallet,
            withdrawal=withdrawal,
            type=Transaction.Type.WITHDRAWAL_CAPTURE,
            amount=-200,
            status=Transaction.Status.SUCCESS,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Transaction.objects.create(
                    wallet=wallet,
                    withdrawal=withdrawal,
                    type=Transaction.Type.WITHDRAWAL_CAPTURE,
                    amount=-200,
                    status=Transaction.Status.SUCCESS,
                )

    def test_create_capture_if_missing_returns_existing_capture(self):
        wallet = Wallet.objects.create(balance=500)
        withdrawal = Withdrawal.objects.create(
            wallet=wallet,
            amount=200,
            execute_at=timezone.now() - timedelta(minutes=1),
        )

        first_capture = transaction_repository.create_capture_if_missing(withdrawal)
        second_capture = transaction_repository.create_capture_if_missing(withdrawal)

        self.assertEqual(first_capture.id, second_capture.id)
        self.assertEqual(
            Transaction.objects.filter(
                withdrawal=withdrawal,
                type=Transaction.Type.WITHDRAWAL_CAPTURE,
            ).count(),
            1,
        )

    def test_execute_withdrawal_success_debits_wallet_and_marks_success(self):
        wallet = Wallet.objects.create(balance=500)
        withdrawal = Withdrawal.objects.create(
            wallet=wallet,
            amount=200,
            execute_at=timezone.now() - timedelta(minutes=1),
        )
        client = FakeTransferClient(
            TransferResult(
                status=TransferStatus.SUCCESS,
                http_status=200,
                response_payload={"data": "success", "status": 200},
            )
        )

        result = execute_withdrawal(withdrawal.id, client=client)

        wallet.refresh_from_db()
        self.assertEqual(result.status, Withdrawal.Status.SUCCESS)
        self.assertEqual(wallet.balance, 300)
        self.assertEqual(len(client.calls), 1)
        self.assertTrue(
            Transaction.objects.filter(
                withdrawal=withdrawal,
                type=Transaction.Type.WITHDRAWAL_RESERVATION,
                status=Transaction.Status.SUCCESS,
            ).exists()
        )
        self.assertTrue(
            Transaction.objects.filter(
                withdrawal=withdrawal,
                type=Transaction.Type.WITHDRAWAL_CAPTURE,
                status=Transaction.Status.SUCCESS,
            ).exists()
        )

    def test_execute_withdrawal_insufficient_funds_fails_without_external_call(self):
        wallet = Wallet.objects.create(balance=100)
        withdrawal = Withdrawal.objects.create(
            wallet=wallet,
            amount=200,
            execute_at=timezone.now() - timedelta(minutes=1),
        )
        client = FakeTransferClient(TransferResult(status=TransferStatus.SUCCESS))

        result = execute_withdrawal(withdrawal.id, client=client)

        wallet.refresh_from_db()
        self.assertEqual(result.status, Withdrawal.Status.FAILED)
        self.assertEqual(result.failure_reason, "Insufficient funds.")
        self.assertEqual(wallet.balance, 100)
        self.assertEqual(client.calls, [])

    def test_execute_withdrawal_explicit_failure_refunds_wallet(self):
        wallet = Wallet.objects.create(balance=500)
        withdrawal = Withdrawal.objects.create(
            wallet=wallet,
            amount=200,
            execute_at=timezone.now() - timedelta(minutes=1),
        )
        client = FakeTransferClient(
            TransferResult(
                status=TransferStatus.FAILED,
                http_status=200,
                response_payload={"data": "failed", "status": 503},
                error_message="failed",
            )
        )

        result = execute_withdrawal(withdrawal.id, client=client)

        wallet.refresh_from_db()
        self.assertEqual(result.status, Withdrawal.Status.FAILED)
        self.assertEqual(wallet.balance, 500)
        self.assertTrue(
            Transaction.objects.filter(
                withdrawal=withdrawal,
                type=Transaction.Type.WITHDRAWAL_REFUND,
                status=Transaction.Status.SUCCESS,
            ).exists()
        )

    def test_execute_withdrawal_unknown_keeps_reserved_funds(self):
        wallet = Wallet.objects.create(balance=500)
        withdrawal = Withdrawal.objects.create(
            wallet=wallet,
            amount=200,
            execute_at=timezone.now() - timedelta(minutes=1),
        )
        client = FakeTransferClient(TransferResult(status=TransferStatus.UNKNOWN, error_message="timeout"))

        result = execute_withdrawal(withdrawal.id, client=client)

        wallet.refresh_from_db()
        self.assertEqual(result.status, Withdrawal.Status.UNKNOWN)
        self.assertEqual(wallet.balance, 300)
        self.assertFalse(
            Transaction.objects.filter(
                withdrawal=withdrawal,
                type=Transaction.Type.WITHDRAWAL_REFUND,
            ).exists()
        )

    def test_two_withdrawals_do_not_overdraw_wallet(self):
        wallet = Wallet.objects.create(balance=300)
        first = Withdrawal.objects.create(
            wallet=wallet,
            amount=200,
            execute_at=timezone.now() - timedelta(minutes=1),
        )
        second = Withdrawal.objects.create(
            wallet=wallet,
            amount=200,
            execute_at=timezone.now() - timedelta(minutes=1),
        )
        client = FakeTransferClient(TransferResult(status=TransferStatus.SUCCESS, http_status=200))

        first_result = execute_withdrawal(first.id, client=client)
        second_result = execute_withdrawal(second.id, client=client)

        wallet.refresh_from_db()
        self.assertEqual(first_result.status, Withdrawal.Status.SUCCESS)
        self.assertEqual(second_result.status, Withdrawal.Status.FAILED)
        self.assertEqual(wallet.balance, 100)

    def test_claim_due_withdrawal_ids_ignores_future_withdrawals(self):
        wallet = Wallet.objects.create()
        due = Withdrawal.objects.create(
            wallet=wallet,
            amount=100,
            execute_at=timezone.now() - timedelta(minutes=1),
        )
        Withdrawal.objects.create(
            wallet=wallet,
            amount=100,
            execute_at=timezone.now() + timedelta(minutes=1),
        )

        self.assertEqual(claim_due_withdrawal_ids(), [due.id])

    def test_recover_stale_processing_without_reservation_retries(self):
        wallet = Wallet.objects.create()
        withdrawal = Withdrawal.objects.create(
            wallet=wallet,
            amount=100,
            status=Withdrawal.Status.PROCESSING,
            execute_at=timezone.now() - timedelta(minutes=10),
            locked_at=timezone.now() - timedelta(minutes=10),
        )

        recovered_ids = recover_stale_processing_withdrawals(timeout_seconds=60)

        withdrawal.refresh_from_db()
        self.assertEqual(recovered_ids, [withdrawal.id])
        self.assertEqual(withdrawal.status, Withdrawal.Status.RETRYING)

    def test_recover_stale_processing_with_reservation_marks_unknown(self):
        wallet = Wallet.objects.create(balance=100)
        withdrawal = Withdrawal.objects.create(
            wallet=wallet,
            amount=100,
            status=Withdrawal.Status.PROCESSING,
            execute_at=timezone.now() - timedelta(minutes=10),
            locked_at=timezone.now() - timedelta(minutes=10),
        )
        Transaction.objects.create(
            wallet=wallet,
            withdrawal=withdrawal,
            type=Transaction.Type.WITHDRAWAL_RESERVATION,
            amount=-100,
            status=Transaction.Status.SUCCESS,
        )

        recovered_ids = recover_stale_processing_withdrawals(timeout_seconds=60)

        withdrawal.refresh_from_db()
        self.assertEqual(recovered_ids, [])
        self.assertEqual(withdrawal.status, Withdrawal.Status.UNKNOWN)
