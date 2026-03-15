"""Schemas for the Query Intelligence Layer (advanced search)."""
from pydantic import BaseModel, Field


# Intent and domain enums (values returned by LLM)
QUERY_INTENTS = (
    "factual_lookup",
    "policy_entitlement",
    "approval_workflow",
    "comparison",
    "calculation",
    "exception_handling",
    "unsupported",
    "general",
)
DOMAINS = ("HR", "Compliance", "Finance", "Legal", "Pricing", "Technical", "General")


class QueryIntelligenceFilters(BaseModel):
    """Structured filters extracted from the question (for retrieval)."""
    leave_type: str | None = None       # e.g. sick_leave, casual_leave
    employee_type: str | None = None   # e.g. new_employee, contractor
    geography: str | None = None       # e.g. India, US
    regulation: str | None = None      # e.g. Factories Act
    policy_year: str | None = None     # e.g. current_year, 2024
    doc_type: str | None = None        # e.g. policy, contract
    extra: dict = Field(default_factory=dict)  # any other key-value filters


class SearchPlanStep(BaseModel):
    """One step in the search plan."""
    action: str  # vector_only | hybrid | search_folder | policy_docs_only | split_subqueries | ask_clarification
    value: str | list[str] | None = None  # e.g. folder path, or list of subqueries, or clarification question


class QueryIntelligenceResult(BaseModel):
    """Full output of the Query Intelligence Layer."""
    # 1. Query cleanup
    cleaned_query: str = ""
    original_query: str = ""

    # 2. Query intent
    intent: str = "general"  # factual_lookup | policy_entitlement | approval_workflow | comparison | calculation | exception_handling | unsupported | general
    intent_confidence: float = 0.0  # 0-1

    # 3. Query splitting (compound -> multiple)
    sub_queries: list[str] = Field(default_factory=list)  # if compound, one per intent; else [cleaned_query]

    # 4. Query rewriting (search variants for better recall)
    search_variants: list[str] = Field(default_factory=list)  # 3-6 alternative phrasings for retrieval

    # 5. Domain detection
    domain: str = "General"  # HR | Compliance | Finance | Legal | Pricing | Technical | General
    domain_confidence: float = 0.0  # 0-1

    # 6. Filter extraction
    filters: QueryIntelligenceFilters = Field(default_factory=QueryIntelligenceFilters)

    # 7. Clarification detection
    clarification_status: str = "search_ready"  # search_ready | clarification_needed
    clarification_reason: str | None = None
    suggested_clarification_questions: list[str] = Field(default_factory=list)

    # 8. Search plan (agentic decision)
    search_plan_steps: list[SearchPlanStep] = Field(default_factory=list)
    # Derived: single list of queries to run (after split + rewrite), for retrieval
    queries_for_retrieval: list[str] = Field(default_factory=list)

    # Backward compatibility with existing QueryAnalysis (reasoning pipeline)
    def to_query_analysis_dict(self) -> dict:
        """Convert to dict compatible with reasoning's query_analysis."""
        constraints: dict = {}
        if self.filters:
            d = self.filters.model_dump(exclude_none=True)
            extra = d.pop("extra", {})
            if isinstance(extra, dict):
                constraints = {**d, **extra}
            else:
                constraints = d
        return {
            "intent": self.intent,
            "domain": self.domain,
            "answer_type": self._answer_type_from_intent(),
            "constraints": constraints,
            "missing_constraints": self.suggested_clarification_questions or [],
        }

    def _answer_type_from_intent(self) -> str:
        if self.intent == "comparison":
            return "comparison"
        if self.intent == "calculation":
            return "step-by-step"
        if self.intent in ("policy_entitlement", "approval_workflow"):
            return "clause-based"
        return "short fact"
