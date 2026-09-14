from django.contrib import admin

from wallets.models import Transaction, Wallet, Withdrawal


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ("uuid", "balance", "created_at", "updated_at", "deleted_at")
    search_fields = ("uuid",)
    readonly_fields = ("created_at", "updated_at")
    ordering = ("-created_at",)


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ("id", "wallet", "withdrawal", "type", "amount", "status", "created_at")
    list_filter = ("type", "status", "created_at")
    search_fields = ("wallet__uuid", "withdrawal__id")
    readonly_fields = ("created_at", "updated_at")
    ordering = ("-created_at",)
    autocomplete_fields = ("wallet", "withdrawal")


@admin.register(Withdrawal)
class WithdrawalAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "wallet",
        "amount",
        "status",
        "execute_at",
        "attempt_count",
        "locked_at",
        "processed_at",
        "created_at",
    )
    list_filter = ("status", "execute_at", "created_at")
    search_fields = ("wallet__uuid",)
    readonly_fields = ("created_at", "updated_at")
    ordering = ("-created_at",)
    autocomplete_fields = ("wallet",)
