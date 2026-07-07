from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from apps.transactions.models import Transaction
from apps.enrichment import documents


class DashboardView(APIView):

    def get(self, request):

        # lookup
        flagged = Transaction.objects.filter(
            status__in=["NEEDS_REVIEW", "AUTO_BLOCK"]
        ).order_by("-created_at")

        enrichments = documents.find_by_transaction_ids([t.id for t in flagged])

        results = []
        for tx in flagged:
            enrichment = enrichments.get(str(tx.id), {})
            results.append({
                "transaction_id": str(tx.id),
                "status": tx.status,
                "risk_score": tx.risk_score,
                "reasons": tx.reasons,
                "merchant_name": tx.merchant_name,
                "amount": tx.amount,
                "currency": tx.currency,
                "created_at": tx.created_at.isoformat(),
                "explanation": enrichment.get("explanation"),
                "enrichment_status": enrichment.get("enrichment_status", "QUEUED"),
                "investigation_trace": enrichment.get("investigation_trace"),
            })

        return Response(results, status=status.HTTP_200_OK)
