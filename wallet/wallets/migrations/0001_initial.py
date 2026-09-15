# Generated manually to match the wallet service implementation.

import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Wallet",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("uuid", models.UUIDField(db_index=True, default=uuid.uuid4, unique=True)),
                ("balance", models.BigIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name="Withdrawal",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("amount", models.BigIntegerField()),
                ("execute_at", models.DateTimeField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("processing", "Processing"),
                            ("success", "Success"),
                            ("failed", "Failed"),
                            ("unknown", "Unknown"),
                            ("retrying", "Retrying"),
                        ],
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("failure_reason", models.TextField(blank=True)),
                ("attempt_count", models.PositiveIntegerField(default=0)),
                ("locked_at", models.DateTimeField(blank=True, null=True)),
                ("processed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "wallet",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="withdrawals",
                        to="wallets.wallet",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="Transaction",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "type",
                    models.CharField(
                        choices=[
                            ("deposit", "Deposit"),
                            ("withdrawal_reservation", "Withdrawal reservation"),
                            ("withdrawal_capture", "Withdrawal capture"),
                            ("withdrawal_refund", "Withdrawal refund"),
                        ],
                        max_length=32,
                    ),
                ),
                ("amount", models.BigIntegerField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("success", "Success"),
                            ("failed", "Failed"),
                        ],
                        default="success",
                        max_length=16,
                    ),
                ),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "wallet",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="transactions",
                        to="wallets.wallet",
                    ),
                ),
                (
                    "withdrawal",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="transactions",
                        to="wallets.withdrawal",
                    ),
                ),
            ],
        ),
        migrations.AddIndex(
            model_name="transaction",
            index=models.Index(fields=["wallet", "created_at"], name="wallets_tra_wallet__3b7555_idx"),
        ),
        migrations.AddIndex(
            model_name="transaction",
            index=models.Index(fields=["withdrawal", "type"], name="wallets_tra_withdra_43a90a_idx"),
        ),
        migrations.AddIndex(
            model_name="transaction",
            index=models.Index(fields=["type", "status"], name="wallets_tra_type_7df550_idx"),
        ),
        migrations.AddIndex(
            model_name="transaction",
            index=models.Index(fields=["created_at"], name="wallets_tra_created_486ff3_idx"),
        ),
        migrations.AddIndex(
            model_name="withdrawal",
            index=models.Index(fields=["status", "execute_at"], name="wallets_wit_status_43a5ee_idx"),
        ),
        migrations.AddIndex(
            model_name="withdrawal",
            index=models.Index(fields=["wallet", "status"], name="wallets_wit_wallet__930b2a_idx"),
        ),
        migrations.AddIndex(
            model_name="withdrawal",
            index=models.Index(fields=["locked_at"], name="wallets_wit_locked__7ba81e_idx"),
        ),
        migrations.AddConstraint(
            model_name="wallet",
            constraint=models.CheckConstraint(check=models.Q(("balance__gte", 0)), name="wallet_balance_non_negative"),
        ),
        migrations.AddConstraint(
            model_name="transaction",
            constraint=models.CheckConstraint(
                check=models.Q(("amount", 0), _negated=True), name="wallet_transaction_amount_not_zero"
            ),
        ),
        migrations.AddConstraint(
            model_name="withdrawal",
            constraint=models.CheckConstraint(check=models.Q(("amount__gt", 0)), name="withdrawal_amount_positive"),
        ),
    ]
