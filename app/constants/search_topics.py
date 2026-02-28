"""Fixed list of topics for search answer classification (RAG)."""

SEARCH_ANSWER_TOPICS = (
    "Payment terms",
    "SLA requirements",
    "Security compliance",
    "Pricing structure",
    "Delivery schedule",
    "Liability and indemnification",
    "Warranty and support",
    "Data privacy and GDPR",
    "Termination and renewal",
    "Scope of work / SOW",
)

TOPIC_OTHER = "Other"

def is_valid_topic(topic: str | None) -> bool:
    """Return True if topic is in the allowed list."""
    if not topic or not topic.strip():
        return False
    return topic.strip() in SEARCH_ANSWER_TOPICS

def normalize_topic(topic: str | None) -> str:
    """Return topic if valid, else TOPIC_OTHER."""
    if is_valid_topic(topic):
        return (topic or "").strip()
    return TOPIC_OTHER
