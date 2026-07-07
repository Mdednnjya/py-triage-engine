import json
import logging

import requests
from decouple import config

from apps.enrichment.tools import TOOL_SCHEMA, TOOL_REGISTRY

logger = logging.getLogger(__name__)


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

_INVESTIGATOR_SYSTEM_PROMPT = (
    "You are a financial risk analyst investigating a flagged transaction in more depth. "
    "A first-pass assessment already exists but its confidence was low or medium. "
    "You have read-only tools available to pull the user's transaction history, "
    "the user's past flags, and merchant-wide flag stats. Call a tool when you need "
    "more context; otherwise respond with the final verdict. "
    "Always respond with valid JSON only when issuing a verdict. No preamble, no markdown, "
    "no code fences, no explanation outside the JSON object. "
    "Never deviate from the required structure: "
    '{"summary": "...", "risk_factors": [...], "recommended_action": "...", "confidence": "..."} '
    "confidence definition: "
    "high: risk_score >= 50 or critical rule triggered; "
    "medium: risk_score 30-49, multiple rules triggered; "
    "low: borderline score, single rule triggered"
)


class CircuitOpenError(Exception):
    pass


def investigate(transaction, first_pass_result):

    from apps.enrichment import circuit_breaker

    messages = [
        {"role": "system", "content": _INVESTIGATOR_SYSTEM_PROMPT},
        {"role": "user", "content": _build_prompt(transaction, first_pass_result)},
    ]

    tool_calls_summary = []
    max_iterations = int(config("AGENT_MAX_ITERATIONS", default=3))

    for iteration in range(max_iterations):

        # checker
        if not circuit_breaker.allow_request():
            raise CircuitOpenError()

        message = _call_llm(messages)

        if message.get("tool_calls"):

            messages.append({
                "role": "assistant",
                "content": message.get("content"),
                "tool_calls": message["tool_calls"],
            })

            for call in message["tool_calls"]:
                name = call["function"]["name"]
                args = json.loads(call["function"]["arguments"])
                result = TOOL_REGISTRY[name](**args)
                tool_calls_summary.append({"tool": name, "args": args})

                messages.append({
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": json.dumps(result),
                })

            continue

        return {
            "explanation": _parse_verdict(message.get("content", "")),
            "iterations": iteration + 1,
            "tool_calls": tool_calls_summary,
        }

    # checker
    if not circuit_breaker.allow_request():
        raise CircuitOpenError()

    messages.append({"role": "user", "content": "finalize now with available information"})
    message = _call_llm(messages)

    return {
        "explanation": _parse_verdict(message.get("content", "")),
        "iterations": max_iterations,
        "tool_calls": tool_calls_summary,
    }


def _call_llm(messages):

    response = requests.post(
        OPENROUTER_URL,
        headers={
            "Authorization": f"Bearer {config('OPENROUTER_API_KEY', default='')}",
            "Content-Type": "application/json",
        },
        json={
            "model": config("OPENROUTER_MODEL", default="mistral/mistral-7b-instruct"),
            "messages": messages,
            "tools": TOOL_SCHEMA,
            "stream": False,
        },
        timeout=30,
    )

    response.raise_for_status()

    return response.json()["choices"][0]["message"]


def _parse_verdict(content):

    content = content.strip()

    # strip markdown code fences if model ignores instruction
    if content.startswith("```"):
        content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        logger.error("malformed json from llm: %s", content)
        raise


def _build_prompt(transaction, first_pass_result):

    rules = ", ".join(transaction.reasons) if transaction.reasons else "none"
    return (
        f"A payment transaction was flagged for review.\n\n"
        f"Amount: {transaction.amount} {transaction.currency}\n"
        f"Merchant: {transaction.merchant_name}\n"
        f"Location: {transaction.location}\n"
        f"Risk score: {transaction.risk_score}\n"
        f"Triggered rules: {rules}\n"
        f"User id: {transaction.user_id}\n\n"
        f"First-pass assessment:\n{json.dumps(first_pass_result)}"
    )
