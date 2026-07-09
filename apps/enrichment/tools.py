from datetime import timedelta

from django.utils import timezone


def get_user_transaction_history(user_id, window_days=30):

    from apps.transactions.models import Transaction

    cutoff = timezone.now() - timedelta(days=window_days)

    # lookup
    qs = Transaction.objects.filter(
        user_id=user_id,
        created_at__gte=cutoff,
    ).order_by("-created_at")[:20]

    return [
        {
            "amount": tx.amount,
            "currency": tx.currency,
            "merchant_name": tx.merchant_name,
            "status": tx.status,
            "risk_score": tx.risk_score,
            "created_at": tx.created_at.isoformat(),
        }
        for tx in qs
    ]


def get_user_flag_history(user_id):

    from apps.transactions.models import Transaction

    # lookup
    qs = Transaction.objects.filter(
        user_id=user_id,
        status__in=["NEEDS_REVIEW", "AUTO_BLOCK"],
    ).order_by("-created_at")[:10]

    return [
        {
            "amount": tx.amount,
            "status": tx.status,
            "risk_score": tx.risk_score,
            "reasons": tx.reasons,
            "created_at": tx.created_at.isoformat(),
        }
        for tx in qs
    ]


def get_merchant_flag_stats(merchant_name):

    from apps.transactions.models import Transaction

    # lookup
    qs = Transaction.objects.filter(merchant_name=merchant_name)

    return {
        "total_count": qs.count(),
        "flagged_count": qs.filter(status="NEEDS_REVIEW").count(),
        "blocked_count": qs.filter(status="AUTO_BLOCK").count(),
    }


TOOL_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "get_user_transaction_history",
            "description": "Get recent transaction history for a user, most recent first, capped at 20 records.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string", "description": "the user to look up"},
                    "window_days": {"type": "integer", "description": "how many days back to search, defaults to 30"},
                },
                "required": ["user_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_user_flag_history",
            "description": "Get past transactions for a user that were flagged NEEDS_REVIEW or AUTO_BLOCK, most recent first, capped at 10 records.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string", "description": "the user to look up"},
                },
                "required": ["user_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_merchant_flag_stats",
            "description": "Get aggregate transaction counts for a merchant across all users: total, flagged, and blocked.",
            "parameters": {
                "type": "object",
                "properties": {
                    "merchant_name": {"type": "string", "description": "the merchant to look up"},
                },
                "required": ["merchant_name"],
            },
        },
    },
]

TOOL_REGISTRY = {
    "get_user_transaction_history": get_user_transaction_history,
    "get_user_flag_history": get_user_flag_history,
    "get_merchant_flag_stats": get_merchant_flag_stats,
}
