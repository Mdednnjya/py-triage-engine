import uuid
from django.db import models


class Transaction(models.Model):

    STATUS_CHOICES = [
        ("AUTO_APPROVE", "Auto Approve"),
        ("NEEDS_REVIEW", "Needs Review"),
        ("AUTO_BLOCK", "Auto Block"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    amount = models.BigIntegerField()
    currency = models.CharField(max_length=3)
    user_id = models.CharField(max_length=255)
    merchant_name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    memo = models.TextField(blank=True)
    location = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    risk_score = models.IntegerField(default=0)
    reasons = models.JSONField(default=list)
    idempotency_key = models.CharField(max_length=255, unique=True)
    enrichment_queued = models.BooleanField(default=False)
    request_id = models.CharField(max_length=36, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user_id", "created_at"]),
            models.Index(fields=["merchant_name"]),
        ]


class IdempotencyKey(models.Model):

    key = models.CharField(max_length=255, unique=True)
    transaction = models.OneToOneField(Transaction, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
