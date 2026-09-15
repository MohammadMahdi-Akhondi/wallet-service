from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from wallets.infrastructure.third_party import TransferResult, TransferStatus
from wallets.models import Transaction, Wallet, Withdrawal
from wallets.services import withdrawal_service


class FakeTransferClient:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def transfer(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


class WithdrawalServiceIntegrationTests(TestCase):
    def test_schedule_withdrawal_persists_pending_record_and_enqueues_after_commit(self):
        wallet = Wallet.objects.create(balance=50)
        execute_at = timezone.now() + timedelta(minutes=10)

        with patch("wallets.tasks.execute_withdrawal.apply_async") as apply_async, self.captureOnCommitCallbacks(
            execute=True
        ):
            withdrawal = withdrawal_service.schedule_withdrawal(wallet.uuid, 25, execute_at)

        withdrawal.refresh_from_db()
        self.assertEqual(withdrawal.wallet_id, wallet.id)
        self.assertEqual(withdrawal.amount, 25)
        self.assertEqual(withdrawal.execute_at, execute_at)
        self.assertEqual(withdrawal.status, Withdrawal.Status.PENDING)
        self.assertEqual(withdrawal.attempt_count, 0)
        self.assertEqual(Transaction.objects.count(), 0)
        apply_async.assert_called_once_with(args=[withdrawal.id], eta=execute_at)

    def test_execute_withdrawal_success_reserves_calls_client_and_captures_once(self):
        wallet = Wallet.objects.create(balance=500)
        withdrawal = Withdrawal.objects.create(
            wallet=wallet,
            amount=125,
            execute_at=timezone.now() - timedelta(minutes=1),
        )
        client = FakeTransferClient(TransferResult(status=TransferStatus.SUCCESS, http_status=200))

        result = withdrawal_service.execute_withdrawal(withdrawal.id, client=client)

        wallet.refresh_from_db()
        withdrawal.refresh_from_db()
        self.assertEqual(result.status, Withdrawal.Status.SUCCESS)
        self.assertEqual(withdrawal.status, Withdrawal.Status.SUCCESS)
        self.assertEqual(withdrawal.attempt_count, 1)
        self.assertIsNotNone(withdrawal.locked_at)
        self.assertIsNotNone(withdrawal.processed_at)
        self.assertEqual(wallet.balance, 375)
        self.assertEqual(
            client.calls,
            [{"wallet_uuid": wallet.uuid, "amount": 125, "withdrawal_id": withdrawal.id}],
        )
        self.assertEqual(
            list(
                Transaction.objects.filter(withdrawal=withdrawal)
                .order_by("type")
                .values_list("type", "amount", "status")
            ),
            [
                (Transaction.Type.WITHDRAWAL_CAPTURE, -125, Transaction.Status.SUCCESS),
                (Transaction.Type.WITHDRAWAL_RESERVATION, -125, Transaction.Status.SUCCESS),
            ],
        )

    def test_execute_withdrawal_is_idempotent_after_success(self):
        wallet = Wallet.objects.create(balance=500)
        withdrawal = Withdrawal.objects.create(
            wallet=wallet,
            amount=200,
            execute_at=timezone.now() - timedelta(minutes=1),
        )
        client = FakeTransferClient(TransferResult(status=TransferStatus.SUCCESS, http_status=200))

        first = withdrawal_service.execute_withdrawal(withdrawal.id, client=client)
        second = withdrawal_service.execute_withdrawal(withdrawal.id, client=client)

        wallet.refresh_from_db()
        withdrawal.refresh_from_db()
        self.assertEqual(first.status, Withdrawal.Status.SUCCESS)
        self.assertEqual(second.status, Withdrawal.Status.SUCCESS)
        self.assertEqual(wallet.balance, 300)
        self.assertEqual(withdrawal.attempt_count, 1)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(
            Transaction.objects.filter(
                withdrawal=withdrawal,
                type=Transaction.Type.WITHDRAWAL_RESERVATION,
            ).count(),
            1,
        )
        self.assertEqual(
            Transaction.objects.filter(
                withdrawal=withdrawal,
                type=Transaction.Type.WITHDRAWAL_CAPTURE,
            ).count(),
            1,
        )

    def test_execute_withdrawal_insufficient_funds_records_failed_reservation_without_client_call(self):
        wallet = Wallet.objects.create(balance=99)
        withdrawal = Withdrawal.objects.create(
            wallet=wallet,
            amount=100,
            execute_at=timezone.now() - timedelta(minutes=1),
        )
        client = FakeTransferClient(TransferResult(status=TransferStatus.SUCCESS))

        result = withdrawal_service.execute_withdrawal(withdrawal.id, client=client)

        wallet.refresh_from_db()
        self.assertEqual(result.status, Withdrawal.Status.FAILED)
        self.assertEqual(result.failure_reason, "Insufficient funds.")
        self.assertEqual(wallet.balance, 99)
        self.assertEqual(client.calls, [])
        reservation = Transaction.objects.get(
            withdrawal=withdrawal,
            type=Transaction.Type.WITHDRAWAL_RESERVATION,
        )
        self.assertEqual(reservation.status, Transaction.Status.FAILED)
        self.assertEqual(reservation.amount, -100)
        self.assertEqual(reservation.metadata, {"reason": "insufficient_funds"})

    def test_execute_withdrawal_explicit_external_failure_refunds_reserved_amount_once(self):
        wallet = Wallet.objects.create(balance=500)
        withdrawal = Withdrawal.objects.create(
            wallet=wallet,
            amount=175,
            execute_at=timezone.now() - timedelta(minutes=1),
        )
        client = FakeTransferClient(
            TransferResult(status=TransferStatus.FAILED, http_status=400, error_message="declined")
        )

        result = withdrawal_service.execute_withdrawal(withdrawal.id, client=client)
        repeated = withdrawal_service.execute_withdrawal(withdrawal.id, client=client)

        wallet.refresh_from_db()
        self.assertEqual(result.status, Withdrawal.Status.FAILED)
        self.assertEqual(result.failure_reason, "declined")
        self.assertEqual(repeated.status, Withdrawal.Status.FAILED)
        self.assertEqual(wallet.balance, 500)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(
            Transaction.objects.filter(
                withdrawal=withdrawal,
                type=Transaction.Type.WITHDRAWAL_REFUND,
                status=Transaction.Status.SUCCESS,
            ).count(),
            1,
        )

    def test_execute_withdrawal_unknown_keeps_reserved_funds_without_refund_or_capture(self):
        wallet = Wallet.objects.create(balance=500)
        withdrawal = Withdrawal.objects.create(
            wallet=wallet,
            amount=175,
            execute_at=timezone.now() - timedelta(minutes=1),
        )
        client = FakeTransferClient(TransferResult(status=TransferStatus.UNKNOWN, error_message="timeout"))

        result = withdrawal_service.execute_withdrawal(withdrawal.id, client=client)

        wallet.refresh_from_db()
        self.assertEqual(result.status, Withdrawal.Status.UNKNOWN)
        self.assertEqual(result.failure_reason, "timeout")
        self.assertEqual(wallet.balance, 325)
        self.assertTrue(
            Transaction.objects.filter(
                withdrawal=withdrawal,
                type=Transaction.Type.WITHDRAWAL_RESERVATION,
                status=Transaction.Status.SUCCESS,
            ).exists()
        )
        self.assertFalse(
            Transaction.objects.filter(
                withdrawal=withdrawal,
                type__in=[Transaction.Type.WITHDRAWAL_CAPTURE, Transaction.Type.WITHDRAWAL_REFUND],
            ).exists()
        )

    def test_execute_withdrawal_retrying_due_withdrawal_can_be_executed(self):
        wallet = Wallet.objects.create(balance=250)
        withdrawal = Withdrawal.objects.create(
            wallet=wallet,
            amount=100,
            status=Withdrawal.Status.RETRYING,
            failure_reason="previous worker stopped",
            execute_at=timezone.now() - timedelta(minutes=1),
        )
        client = FakeTransferClient(TransferResult(status=TransferStatus.SUCCESS, http_status=200))

        result = withdrawal_service.execute_withdrawal(withdrawal.id, client=client)

        wallet.refresh_from_db()
        withdrawal.refresh_from_db()
        self.assertEqual(result.status, Withdrawal.Status.SUCCESS)
        self.assertEqual(withdrawal.failure_reason, "")
        self.assertEqual(withdrawal.attempt_count, 1)
        self.assertEqual(wallet.balance, 150)

    def test_execute_withdrawal_future_or_terminal_status_does_not_call_client(self):
        wallet = Wallet.objects.create(balance=250)
        future = Withdrawal.objects.create(
            wallet=wallet,
            amount=100,
            execute_at=timezone.now() + timedelta(minutes=1),
        )
        terminal = Withdrawal.objects.create(
            wallet=wallet,
            amount=100,
            status=Withdrawal.Status.FAILED,
            execute_at=timezone.now() - timedelta(minutes=1),
        )
        client = FakeTransferClient(TransferResult(status=TransferStatus.SUCCESS, http_status=200))

        future_result = withdrawal_service.execute_withdrawal(future.id, client=client)
        terminal_result = withdrawal_service.execute_withdrawal(terminal.id, client=client)

        wallet.refresh_from_db()
        self.assertEqual(future_result.status, Withdrawal.Status.PENDING)
        self.assertEqual(terminal_result.status, Withdrawal.Status.FAILED)
        self.assertEqual(wallet.balance, 250)
        self.assertEqual(client.calls, [])

    def test_claim_due_withdrawal_ids_returns_due_pending_and_retrying_ordered_by_execute_at(self):
        wallet = Wallet.objects.create()
        later_pending = Withdrawal.objects.create(
            wallet=wallet,
            amount=10,
            execute_at=timezone.now() - timedelta(minutes=1),
        )
        due_retrying = Withdrawal.objects.create(
            wallet=wallet,
            amount=10,
            status=Withdrawal.Status.RETRYING,
            execute_at=timezone.now() - timedelta(minutes=2),
        )
        Withdrawal.objects.create(
            wallet=wallet,
            amount=10,
            status=Withdrawal.Status.PROCESSING,
            execute_at=timezone.now() - timedelta(minutes=3),
        )
        Withdrawal.objects.create(
            wallet=wallet,
            amount=10,
            execute_at=timezone.now() + timedelta(minutes=1),
        )

        self.assertEqual(
            withdrawal_service.claim_due_withdrawal_ids(limit=10),
            [due_retrying.id, later_pending.id],
        )
        self.assertEqual(withdrawal_service.claim_due_withdrawal_ids(limit=1), [due_retrying.id])

    def test_recover_stale_processing_retries_only_unreserved_stale_withdrawals(self):
        wallet = Wallet.objects.create(balance=300)
        stale_without_reservation = Withdrawal.objects.create(
            wallet=wallet,
            amount=100,
            status=Withdrawal.Status.PROCESSING,
            execute_at=timezone.now() - timedelta(minutes=15),
            locked_at=timezone.now() - timedelta(minutes=10),
        )
        stale_with_reservation = Withdrawal.objects.create(
            wallet=wallet,
            amount=100,
            status=Withdrawal.Status.PROCESSING,
            execute_at=timezone.now() - timedelta(minutes=15),
            locked_at=timezone.now() - timedelta(minutes=10),
        )
        fresh_processing = Withdrawal.objects.create(
            wallet=wallet,
            amount=100,
            status=Withdrawal.Status.PROCESSING,
            execute_at=timezone.now() - timedelta(minutes=15),
            locked_at=timezone.now(),
        )
        Transaction.objects.create(
            wallet=wallet,
            withdrawal=stale_with_reservation,
            type=Transaction.Type.WITHDRAWAL_RESERVATION,
            amount=-100,
            status=Transaction.Status.SUCCESS,
        )

        recovered_ids = withdrawal_service.recover_stale_processing_withdrawals(timeout_seconds=60)

        stale_without_reservation.refresh_from_db()
        stale_with_reservation.refresh_from_db()
        fresh_processing.refresh_from_db()
        self.assertEqual(recovered_ids, [stale_without_reservation.id])
        self.assertEqual(stale_without_reservation.status, Withdrawal.Status.RETRYING)
        self.assertEqual(
            stale_without_reservation.failure_reason,
            "Recovered stale processing withdrawal before funds were reserved.",
        )
        self.assertEqual(stale_with_reservation.status, Withdrawal.Status.UNKNOWN)
        self.assertEqual(
            stale_with_reservation.failure_reason,
            "Worker stopped after funds were reserved; external transfer outcome is unknown.",
        )
        self.assertEqual(fresh_processing.status, Withdrawal.Status.PROCESSING)


class WithdrawalApiIntegrationTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_schedule_withdrawal_endpoint_creates_pending_withdrawal(self):
        wallet = Wallet.objects.create(balance=100)
        execute_at = timezone.now() + timedelta(minutes=5)

        with patch("wallets.tasks.execute_withdrawal.apply_async") as apply_async, self.captureOnCommitCallbacks(
            execute=True
        ):
            response = self.client.post(
                f"/v1/wallets/{wallet.uuid}/withdrawal",
                data={"amount": 80, "execute_at": execute_at.isoformat()},
                format="json",
            )

        self.assertEqual(response.status_code, 201)
        withdrawal = Withdrawal.objects.get(wallet=wallet)
        self.assertEqual(response.data["id"], withdrawal.id)
        self.assertEqual(response.data["wallet_uuid"], str(wallet.uuid))
        self.assertEqual(response.data["amount"], 80)
        self.assertEqual(response.data["status"], Withdrawal.Status.PENDING)
        apply_async.assert_called_once_with(args=[withdrawal.id], eta=withdrawal.execute_at)

    def test_schedule_withdrawal_endpoint_validates_amount_execute_at_and_wallet(self):
        wallet = Wallet.objects.create(balance=100)
        future = timezone.now() + timedelta(minutes=5)
        past = timezone.now() - timedelta(minutes=5)
        missing_uuid = "00000000-0000-0000-0000-000000000000"

        invalid_amount = self.client.post(
            f"/v1/wallets/{wallet.uuid}/withdrawal",
            data={"amount": 0, "execute_at": future.isoformat()},
            format="json",
        )
        invalid_execute_at = self.client.post(
            f"/v1/wallets/{wallet.uuid}/withdrawal",
            data={"amount": 10, "execute_at": past.isoformat()},
            format="json",
        )
        missing_wallet = self.client.post(
            f"/v1/wallets/{missing_uuid}/withdrawal",
            data={"amount": 10, "execute_at": future.isoformat()},
            format="json",
        )

        self.assertEqual(invalid_amount.status_code, 400)
        self.assertEqual(invalid_execute_at.status_code, 400)
        self.assertEqual(missing_wallet.status_code, 404)
        self.assertEqual(missing_wallet.data, {"detail": "Wallet not found."})
        self.assertEqual(Withdrawal.objects.count(), 0)
