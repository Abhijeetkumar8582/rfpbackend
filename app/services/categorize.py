"""GPT-based automatic category (cluster) assignment for file repo folders."""
from __future__ import annotations

from app.services.openai_client import get_chat_client

# Default clusters matching your file repo UI (Finance, Security, Architecture, Compliance, Integrations)
DEFAULT_CLUSTERS = [
    "Finance",
    "Security",
    "Architecture",
    "Compliance",
    "Integrations",
]


def categorize_document(text: str, filename: str) -> str:
    """
    Use GPT to assign one category (cluster) from the allowed list.
    Returns cluster name so file is stored in correct folder (project_id/cluster/filename).
    """
    client, model = get_chat_client()

    clusters_str = ", ".join(DEFAULT_CLUSTERS)
    prompt = f"""You are a document classifier for a file repository.
Given the document content (or filename if content is empty), choose exactly ONE category from this list: {clusters_str}.
Reply with only the category name, nothing else. If unclear, pick the best match."""

    content = (text or "").strip() or f"Filename: {filename}"
    content = content[:4_000]  # limit tokens

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": content},
        ],
        max_tokens=50,
    )
    raw = (resp.choices[0].message.content or "").strip()
    # Normalize: match one of the allowed clusters (case-insensitive)
    for c in DEFAULT_CLUSTERS:
        if c.lower() == raw.lower():
            return c
    # If GPT returned something else, use first cluster or "Uncategorized"
    return DEFAULT_CLUSTERS[0] if DEFAULT_CLUSTERS else "Uncategorized"
