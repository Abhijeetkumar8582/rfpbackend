"""Query Intelligence Layer for advanced search.

When advanced search is enabled, runs before retrieval:
1. Query cleanup (spelling, grammar, casing, punctuation)
2. Query intent analysis (factual, policy entitlement, approval workflow, comparison, calculation, exception, unsupported)
3. Query splitting (compound questions -> multiple sub-queries)
4. Query rewriting (stronger search variants for recall)
5. Domain detection (HR, Compliance, Finance, Legal, Pricing, Technical)
6. Filter extraction (leave_type, employee_type, geography, regulation, policy_year)
7. Clarification detection (search_ready vs clarification_needed)
8. Search plan generation (vector_only, hybrid, search_folder, split_subqueries, ask_clarification)
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.config import settings
from app.schemas.query_intelligence import (
    QueryIntelligenceResult,
    QueryIntelligenceFilters,
    SearchPlanStep,
)

logger = logging.getLogger(__name__)

_MAX_QUERY_LEN = 2000


def _sanitize(s: str) -> str:
    if not s:
        return ""
    s = s.replace("\x00", " ")
    return s.encode("utf-8", errors="replace").decode("utf-8")[:_MAX_QUERY_LEN]


def _gpt_json(messages: list[dict], max_tokens: int = 2048) -> dict:
    """Call GPT and parse JSON from response. Returns dict or {} on failure."""
    url = (settings.openai_base_url or "").strip()
    token = (settings.openai_api_key or "").strip()
    if not url or not token:
        raise RuntimeError("OPENAI_BASE_URL and OPENAI_API_KEY are required for query intelligence.")

    body = {
        "model": settings.openai_chat_model,
        "messages": messages,
        "max_tokens": max_tokens,
    }
    if getattr(settings, "openai_send_model_in_body", True):
        body["model"] = settings.openai_chat_model

    import httpx
    with httpx.Client(timeout=60.0) as client:
        r = client.post(url, json=body, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})

    if r.status_code >= 400:
        logger.error("Query intelligence GPT returned %s: %s", r.status_code, (r.text or "")[:500])
        raise RuntimeError(f"GPT returned {r.status_code}: {r.text[:500]}")

    data = r.json()
    choice = (data.get("choices") or [None])[0]
    content = (choice.get("message") or {}).get("content") if choice else ""
    if not content:
        return {}

    text = content.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if match:
        text = match.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def run_query_intelligence(raw_query: str) -> QueryIntelligenceResult:
    """
    Run the full Query Intelligence Layer on the user's raw input.
    Returns a structured result with cleaned query, intent, domain, sub_queries,
    search_variants, filters, clarification_status, and search_plan.
    """
    original = _sanitize((raw_query or "").strip())
    if not original:
        return QueryIntelligenceResult(
            original_query=raw_query or "",
            cleaned_query="",
            queries_for_retrieval=[],
        )

    system = """You are a Query Intelligence Layer in front of a document search system (RFP, policies, HR, compliance).

Analyze the user's question and return a single JSON object with the following structure. Respond with valid JSON only, no markdown.

{
  "cleaned_query": "Normalized question: fix spelling and grammar, expand common abbreviations (EMI -> equated monthly installment, leaves -> leave), fix casing, remove extra punctuation. One clear sentence.",
  "intent": "One of: factual_lookup | policy_entitlement | approval_workflow | comparison | calculation | exception_handling | unsupported | general",
  "intent_confidence": 0.0 to 1.0,
  "sub_queries": ["If the question has multiple distinct parts, split into separate questions. E.g. 'who approves sick leave and who will be replacement' -> ['Who approves sick leave?', 'Who is the replacement during absence?']. Otherwise one element: the cleaned_query."],
  "search_variants": ["3-6 alternative phrasings for better retrieval. Include: cleaned query, keyword-heavy version, policy/formal phrasing, semantic expansion. Each under 100 chars."],
  "domain": "One of: HR | Compliance | Finance | Legal | Pricing | Technical | General",
  "domain_confidence": 0.0 to 1.0,
  "filters": {
    "leave_type": null or "sick_leave" | "casual_leave" | "earned_leave" | etc.,
    "employee_type": null or "new_employee" | "contractor" | etc.,
    "geography": null or "India" | "US" | etc.,
    "regulation": null or "Factories Act" | etc.,
    "policy_year": null or "current_year" | "2024" | etc.,
    "doc_type": null or "policy" | "contract" | etc.,
    "extra": {}
  },
  "clarification_status": "search_ready" or "clarification_needed",
  "clarification_reason": "If clarification_needed, brief reason; else null",
  "suggested_clarification_questions": ["Optional list of questions to ask the user if clarification_needed"],
  "search_plan_steps": [
    {"action": "vector_only" | "hybrid" | "search_folder" | "policy_docs_only" | "split_subqueries" | "ask_clarification", "value": null or string or list of subqueries}
  ]
}

Rules:
- cleaned_query: Fix grammar/spelling, expand abbreviations (EMI, leaves, etc.), normalize casing and punctuation.
- intent: unsupported only if clearly out-of-domain (e.g. weather, sports). Otherwise pick the closest.
- sub_queries: Split only when there are clearly multiple questions (e.g. "X and Y" asking two things). Otherwise [cleaned_query].
- search_variants: Diverse phrasings to improve recall; include policy/entitlement wording when relevant.
- domain: Choose the primary domain the question belongs to; avoids wrong retrieval (e.g. EMI -> Finance, not HR leave docs).
- filters: Extract only what is explicitly or clearly implied in the question; use null when unknown.
- clarification_status: Use clarification_needed when key info is missing (e.g. "how many leaves" without leave type or employee type). Otherwise search_ready.
- search_plan_steps: 1-3 steps. If clarification_needed, first step should be ask_clarification with value = suggested question. If sub_queries length > 1, include split_subqueries. Otherwise vector_only or hybrid.
"""

    user = f"User question: {original}"

    try:
        out = _gpt_json(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=1536,
        )
    except Exception as e:
        logger.warning("Query intelligence LLM failed: %s", e)
        return _fallback_result(original)

    return _parse_intelligence_result(original, out)


def _parse_intelligence_result(original: str, out: dict) -> QueryIntelligenceResult:
    """Build QueryIntelligenceResult from LLM JSON output."""
    cleaned = _str(out.get("cleaned_query")) or original
    intent = _str(out.get("intent")) or "general"
    intent_conf = _float(out.get("intent_confidence"), 0.0)
    sub_q = out.get("sub_queries")
    if not isinstance(sub_q, list):
        sub_q = [cleaned]
    sub_queries = [_str(q) for q in sub_q if _str(q)]
    if not sub_queries:
        sub_queries = [cleaned]

    variants = out.get("search_variants")
    if not isinstance(variants, list):
        variants = [cleaned]
    search_variants = [_str(v) for v in variants if _str(v)][:6]
    if not search_variants:
        search_variants = [cleaned]

    domain = _str(out.get("domain")) or "General"
    domain_conf = _float(out.get("domain_confidence"), 0.0)

    filters_raw = out.get("filters")
    filters = QueryIntelligenceFilters()
    if isinstance(filters_raw, dict):
        filters = QueryIntelligenceFilters(
            leave_type=_str(filters_raw.get("leave_type")),
            employee_type=_str(filters_raw.get("employee_type")),
            geography=_str(filters_raw.get("geography")),
            regulation=_str(filters_raw.get("regulation")),
            policy_year=_str(filters_raw.get("policy_year")),
            doc_type=_str(filters_raw.get("doc_type")),
            extra={k: v for k, v in (filters_raw.get("extra") or {}).items() if isinstance(v, (str, int, float, bool))},
        )

    clarification_status = _str(out.get("clarification_status")) or "search_ready"
    if clarification_status not in ("search_ready", "clarification_needed"):
        clarification_status = "search_ready"
    clarification_reason = _str(out.get("clarification_reason"))
    suggested = out.get("suggested_clarification_questions")
    if not isinstance(suggested, list):
        suggested = []
    suggested_clarification_questions = [_str(q) for q in suggested if _str(q)]

    steps_raw = out.get("search_plan_steps")
    search_plan_steps: list[SearchPlanStep] = []
    if isinstance(steps_raw, list):
        for s in steps_raw:
            if isinstance(s, dict) and _str(s.get("action")):
                val = s.get("value")
                if isinstance(val, list):
                    value: str | list[str] | None = [_str(x) for x in val if _str(x)]
                else:
                    value = _str(val) if val is not None else None
                search_plan_steps.append(SearchPlanStep(action=_str(s.get("action")), value=value or None))

    # Build single list of queries to use for retrieval: prefer sub_queries expanded with variants, dedupe, limit
    seen: set[str] = set()
    queries_for_retrieval: list[str] = []
    for q in sub_queries[:3]:  # max 3 sub-queries
        if q and q not in seen:
            seen.add(q)
            queries_for_retrieval.append(q)
    for v in search_variants:
        if v and v not in seen and len(queries_for_retrieval) < 6:
            seen.add(v)
            queries_for_retrieval.append(v)
    if not queries_for_retrieval:
        queries_for_retrieval = [cleaned]

    return QueryIntelligenceResult(
        original_query=original,
        cleaned_query=cleaned,
        intent=intent,
        intent_confidence=intent_conf,
        sub_queries=sub_queries,
        search_variants=search_variants,
        domain=domain,
        domain_confidence=domain_conf,
        filters=filters,
        clarification_status=clarification_status,
        clarification_reason=clarification_reason or None,
        suggested_clarification_questions=suggested_clarification_questions,
        search_plan_steps=search_plan_steps,
        queries_for_retrieval=queries_for_retrieval,
    )


def _str(x: Any) -> str:
    if x is None:
        return ""
    if isinstance(x, str):
        return x.strip()
    return str(x).strip()


def _float(x: Any, default: float) -> float:
    if x is None:
        return default
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _fallback_result(original: str) -> QueryIntelligenceResult:
    """When LLM fails, return a minimal result that still allows search."""
    return QueryIntelligenceResult(
        original_query=original,
        cleaned_query=original,
        intent="general",
        intent_confidence=0.0,
        sub_queries=[original],
        search_variants=[original],
        domain="General",
        domain_confidence=0.0,
        filters=QueryIntelligenceFilters(),
        clarification_status="search_ready",
        clarification_reason=None,
        suggested_clarification_questions=[],
        search_plan_steps=[SearchPlanStep(action="vector_only", value=None)],
        queries_for_retrieval=[original],
    )
