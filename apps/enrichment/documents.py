from datetime import datetime, timezone

from django.conf import settings
from pymongo import MongoClient


def _collection():

    client = MongoClient(settings.MONGO_URI)
    return client[settings.MONGO_DB]["enrichments"]


def save(transaction_id, explanation, status, model):

    _collection().insert_one({
        "transaction_id": str(transaction_id),
        "explanation": explanation,
        "enrichment_status": status,
        "model": model,
        "created_at": datetime.now(timezone.utc),
    })


def update(transaction_id, status, explanation=None, model=None, investigation_trace=None):

    fields = {"enrichment_status": status}
    if explanation is not None:
        fields["explanation"] = explanation
    if model is not None:
        fields["model"] = model
    if investigation_trace is not None:
        fields["investigation_trace"] = investigation_trace

    _collection().update_one(
        {"transaction_id": str(transaction_id)},
        {"$set": fields},
    )


def update_status_if_not_terminal(transaction_id, status):

    # guard
    _collection().update_one(
        {"transaction_id": str(transaction_id), "enrichment_status": {"$nin": ["COMPLETED", "FAILED"]}},
        {"$set": {"enrichment_status": status}},
    )


def find_pending_older_than(cutoff):

    return list(
        _collection().find(
            {"enrichment_status": "PENDING", "created_at": {"$lt": cutoff}},
            # project
            {"transaction_id": 1, "_id": 0},
        )
    )


def find_by_transaction_ids(transaction_ids):

    ids = [str(tid) for tid in transaction_ids]
    return {
        doc["transaction_id"]: doc
        for doc in _collection().find({"transaction_id": {"$in": ids}})
    }
