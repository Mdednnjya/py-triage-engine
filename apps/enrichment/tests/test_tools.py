import pytest

from apps.enrichment.tools import (
    get_user_transaction_history,
    get_user_flag_history,
    get_merchant_flag_stats,
)


@pytest.mark.django_db
class TestGetUserTransactionHistory:

    def test_returns_recent_transactions(self):

        from apps.transactions.models import Transaction

        # seed
        Transaction.objects.create(
            amount=10_000_000,
            currency="IDR",
            user_id="user-tools-1",
            merchant_name="Merchant A",
            status="AUTO_APPROVE",
            risk_score=0,
            reasons=[],
            idempotency_key="tools-key-1",
        )

        result = get_user_transaction_history("user-tools-1")
        assert len(result) == 1
        assert result[0]["amount"] == 10_000_000
        assert result[0]["merchant_name"] == "Merchant A"

    def test_returns_empty_list_for_no_history(self):

        result = get_user_transaction_history("user-does-not-exist")
        assert result == []


@pytest.mark.django_db
class TestGetUserFlagHistory:

    def test_returns_flagged_transactions_only(self):

        from apps.transactions.models import Transaction

        # seed
        Transaction.objects.create(
            amount=60_000_000,
            currency="IDR",
            user_id="user-tools-2",
            merchant_name="Merchant B",
            status="AUTO_BLOCK",
            risk_score=60,
            reasons=["amount exceeds threshold"],
            idempotency_key="tools-key-2",
        )
        Transaction.objects.create(
            amount=10_000,
            currency="IDR",
            user_id="user-tools-2",
            merchant_name="Merchant B",
            status="AUTO_APPROVE",
            risk_score=0,
            reasons=[],
            idempotency_key="tools-key-3",
        )

        result = get_user_flag_history("user-tools-2")
        assert len(result) == 1
        assert result[0]["status"] == "AUTO_BLOCK"

    def test_returns_empty_list_for_no_flags(self):

        result = get_user_flag_history("user-does-not-exist")
        assert result == []


@pytest.mark.django_db
class TestGetMerchantFlagStats:

    def test_returns_counts(self):

        from apps.transactions.models import Transaction

        # seed
        Transaction.objects.create(
            amount=60_000_000,
            currency="IDR",
            user_id="user-tools-3",
            merchant_name="Merchant C",
            status="AUTO_BLOCK",
            risk_score=60,
            reasons=["amount exceeds threshold"],
            idempotency_key="tools-key-4",
        )
        Transaction.objects.create(
            amount=30_000_000,
            currency="IDR",
            user_id="user-tools-4",
            merchant_name="Merchant C",
            status="NEEDS_REVIEW",
            risk_score=30,
            reasons=["location mismatch"],
            idempotency_key="tools-key-5",
        )
        Transaction.objects.create(
            amount=10_000,
            currency="IDR",
            user_id="user-tools-5",
            merchant_name="Merchant C",
            status="AUTO_APPROVE",
            risk_score=0,
            reasons=[],
            idempotency_key="tools-key-6",
        )

        result = get_merchant_flag_stats("Merchant C")
        assert result["total_count"] == 3
        assert result["flagged_count"] == 1
        assert result["blocked_count"] == 1

    def test_returns_zeroed_counts_for_unknown_merchant(self):

        result = get_merchant_flag_stats("Merchant Does Not Exist")
        assert result == {"total_count": 0, "flagged_count": 0, "blocked_count": 0}
