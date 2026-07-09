import json
from unittest.mock import patch, MagicMock

import pytest

from apps.enrichment import agent


def _fake_transaction():

    from apps.transactions.models import Transaction

    return Transaction(
        amount=60_000_000,
        currency="IDR",
        user_id="user-agent-1",
        merchant_name="Merchant X",
        location="Jakarta",
        status="NEEDS_REVIEW",
        risk_score=40,
        reasons=["location mismatch"],
    )


def _verdict_response(confidence):

    response = MagicMock()
    response.json.return_value = {
        "choices": [{"message": {
            "content": json.dumps({
                "summary": "investigated",
                "risk_factors": ["location mismatch"],
                "recommended_action": "hold",
                "confidence": confidence,
            }),
        }}]
    }
    response.raise_for_status = MagicMock()
    return response


def _tool_call_response(user_id):

    response = MagicMock()
    response.json.return_value = {
        "choices": [{"message": {
            "content": None,
            "tool_calls": [{
                "id": "call_1",
                "type": "function",
                "function": {"name": "get_user_flag_history", "arguments": json.dumps({"user_id": user_id})},
            }],
        }}]
    }
    response.raise_for_status = MagicMock()
    return response


class TestInvestigate:

    def test_returns_verdict_immediately(self):

        transaction = _fake_transaction()

        with patch("apps.enrichment.circuit_breaker.allow_request", return_value=True):
            with patch("apps.enrichment.agent.requests.post", return_value=_verdict_response("high")) as mock_post:
                result = agent.investigate(transaction, {"confidence": "low"})

        assert result["iterations"] == 1
        assert result["tool_calls"] == []
        assert result["explanation"]["confidence"] == "high"
        assert mock_post.call_count == 1

    def test_one_tool_call_then_verdict(self):

        transaction = _fake_transaction()
        mock_tool = MagicMock(return_value=[])

        with patch("apps.enrichment.circuit_breaker.allow_request", return_value=True):
            with patch("apps.enrichment.agent.requests.post", side_effect=[_tool_call_response(transaction.user_id), _verdict_response("high")]) as mock_post:
                with patch("apps.enrichment.agent.TOOL_REGISTRY", {"get_user_flag_history": mock_tool}):
                    result = agent.investigate(transaction, {"confidence": "low"})

        assert result["iterations"] == 2
        assert result["tool_calls"] == [{"tool": "get_user_flag_history", "args": {"user_id": transaction.user_id}}]
        assert mock_post.call_count == 2
        mock_tool.assert_called_once_with(user_id=transaction.user_id)

    def test_cap_reached_forces_finalize(self):

        transaction = _fake_transaction()
        mock_tool = MagicMock(return_value=[])

        responses = [_tool_call_response(transaction.user_id) for _ in range(3)] + [_verdict_response("medium")]

        with patch("apps.enrichment.circuit_breaker.allow_request", return_value=True):
            with patch("apps.enrichment.agent.requests.post", side_effect=responses) as mock_post:
                with patch("apps.enrichment.agent.TOOL_REGISTRY", {"get_user_flag_history": mock_tool}):
                    result = agent.investigate(transaction, {"confidence": "low"})

        assert result["iterations"] == 3
        assert mock_post.call_count == 4
        assert result["explanation"]["confidence"] == "medium"

    def test_circuit_open_mid_loop_raises(self):

        transaction = _fake_transaction()
        mock_tool = MagicMock(return_value=[])

        with patch("apps.enrichment.circuit_breaker.allow_request", side_effect=[True, False]):
            with patch("apps.enrichment.agent.requests.post", return_value=_tool_call_response(transaction.user_id)):
                with patch("apps.enrichment.agent.TOOL_REGISTRY", {"get_user_flag_history": mock_tool}):
                    with pytest.raises(agent.CircuitOpenError):
                        agent.investigate(transaction, {"confidence": "low"})
