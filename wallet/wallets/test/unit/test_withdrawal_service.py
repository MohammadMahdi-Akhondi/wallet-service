from datetime import timedelta
from unittest.mock import Mock, patch

from django.test import SimpleTestCase
from django.utils import timezone

from wallets.exceptions import WalletNotFound
from wallets.infrastructure.third_party import TransferResult, TransferStatus
from wallets.models import Wallet
from wallets.services import withdrawal_service


class WithdrawalServiceUnitTests(SimpleTestCase):
    def test_schedule_withdrawal_rejects_non_positive_amount_before_repository_lookup(self):
        with (
            patch.object(withdrawal_service.wallet_repository, "get_by_uuid") as get_by_uuid,
            self.assertRaisesMessage(ValueError, "Withdrawal amount must be positive."),
        ):
            withdrawal_service.schedule_withdrawal("wallet-uuid", 0, timezone.now() + timedelta(minutes=5))

        get_by_uuid.assert_not_called()

    def test_schedule_withdrawal_rejects_past_execute_at_before_repository_lookup(self):
        with (
            patch.object(withdrawal_service.wallet_repository, "get_by_uuid") as get_by_uuid,
            self.assertRaisesMessage(ValueError, "Execution timestamp must be in the future."),
        ):
            withdrawal_service.schedule_withdrawal("wallet-uuid", 100, timezone.now() - timedelta(seconds=1))

        get_by_uuid.assert_not_called()

    def test_schedule_withdrawal_maps_missing_wallet_to_domain_exception(self):
        with patch.object(
            withdrawal_service.wallet_repository,
            "get_by_uuid",
            side_effect=Wallet.DoesNotExist,
        ), self.assertRaisesMessage(WalletNotFound, "Wallet does not exist."):
            withdrawal_service.schedule_withdrawal("missing-wallet", 100, timezone.now() + timedelta(minutes=5))

    def test_schedule_withdrawal_creates_record_and_registers_on_commit_enqueue(self):
        wallet = Mock()
        withdrawal = Mock()
        execute_at = timezone.now() + timedelta(minutes=5)

        with (
            patch.object(withdrawal_service.wallet_repository, "get_by_uuid", return_value=wallet) as get_by_uuid,
            patch.object(withdrawal_service.withdrawal_repository, "create", return_value=withdrawal) as create,
            patch.object(withdrawal_service.transaction, "on_commit") as on_commit,
        ):
            result = withdrawal_service.schedule_withdrawal("wallet-uuid", "100", execute_at)

        self.assertIs(result, withdrawal)
        get_by_uuid.assert_called_once_with("wallet-uuid")
        create.assert_called_once_with(wallet, 100, execute_at)
        on_commit.assert_called_once()

    def test_claim_due_withdrawal_ids_uses_executable_statuses_and_limit(self):
        first = Mock(id=11)
        second = Mock(id=22)

        with patch.object(
            withdrawal_service.withdrawal_repository,
            "list_locked_due",
            return_value=[first, second],
        ) as list_locked_due, patch.object(withdrawal_service.transaction, "atomic"):
            result = withdrawal_service.claim_due_withdrawal_ids(limit=2)

        self.assertEqual(result, [11, 22])
        _, statuses, limit = list_locked_due.call_args.args
        self.assertEqual(statuses, withdrawal_service.EXECUTABLE_STATUSES)
        self.assertEqual(limit, 2)

    def test_finalize_external_failed_result_refunds_with_default_reason(self):
        result = TransferResult(status=TransferStatus.FAILED)

        with patch.object(withdrawal_service, "_refund_and_fail", return_value="failed") as refund_and_fail:
            self.assertEqual(withdrawal_service._finalize_external_result(12, result), "failed")

        refund_and_fail.assert_called_once_with(12, "Third-party transfer failed.")

    def test_finalize_external_unknown_result_marks_unknown_with_default_reason(self):
        result = TransferResult(status=TransferStatus.UNKNOWN)

        with patch.object(withdrawal_service, "_mark_withdrawal_unknown", return_value="unknown") as mark_unknown:
            self.assertEqual(withdrawal_service._finalize_external_result(12, result), "unknown")

        mark_unknown.assert_called_once_with(12, "External transfer outcome is unknown.")
