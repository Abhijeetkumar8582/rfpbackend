"""GPT-generated document metadata from sampled chunks (title, description, doc_type, tags, taxonomy)."""
from __future__ import annotations

import json
import logging
import re
import random
from typing import Any

from app.services.openai_client import get_chat_client

logger = logging.getLogger(__name__)


def kebab(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"-{2,}", "-", s)
    return s.strip("-")[:40]


def clamp_unique_kebab(tags: list[str], n: int = 15) -> list[str]:
    """Normalize tags to kebab-case, dedupe, return up to n (no placeholder fill)."""
    out: list[str] = []
    seen: set[str] = set()
    for t in tags:
        t = kebab(t)
        if not t or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out[:n]


def sample_chunks(
    chunks: list[dict[str, Any]], max_chunks: int = 12
) -> list[dict[str, Any]]:
    """Balanced sampling: beginning + middle + end + a few random."""
    if len(chunks) <= max_chunks:
        return chunks

    head = chunks[:5]
    tail = chunks[-3:]
    mid_start = max(0, len(chunks) // 2 - 2)
    middle = chunks[mid_start : mid_start + 4]

    pool = [c for c in chunks[5:-3] if c not in middle]
    random.shuffle(pool)
    extra = pool[: max(0, max_chunks - (len(head) + len(middle) + len(tail)))]

    picked = head + middle + tail + extra
    uniq: dict[int, dict[str, Any]] = {}
    for c in picked:
        uniq[int(c.get("chunk_index", 0))] = c
    return [uniq[k] for k in sorted(uniq.keys())][:max_chunks]


def build_context(
    filename: str, chunks: list[dict[str, Any]], max_chars: int = 12000
) -> str:
    lines = [f"FILENAME: {str(filename) if filename is not None else 'document'}"]
    for c in chunks:
        idx = c.get("chunk_index")
        page = c.get("page", 1)
        sec = (c.get("section") or "").strip()
        txt = (c.get("text") or "").strip().replace("\n", " ")
        lines.append(f"[chunk {idx}] [p{page}] [{sec}] {txt[:500]}")
    ctx = "\n".join(lines)
    return ctx[:max_chars]


def gpt_doc_metadata(
    document_id: str, filename: str, context: str
) -> dict[str, Any]:
    """GPT generates title, description, doc_type, tags[15], taxonomy_suggestions."""
    client, model = get_chat_client()

    schema_hint = {
        "document_id": document_id,
        "title": "string (<=120 chars)",
        "description": "string (30-350 chars)",
        "doc_type": "string (one short label)",
        "tags": ["up to 15 kebab-case tags derived FROM the content (topics, entities, domains, document type)"],
        "taxonomy_suggestions": {
            "domains": ["e.g. compliance, finance, hr, legal, operations"],
            "rule_types": ["e.g. policy, procedure, guideline, standard"],
            "applies_to": ["e.g. employees, vendors, products, regions"],
        },
    }

    system = (
        "You generate enterprise knowledge-base metadata from the given document content sample.\n"
        "Return STRICT JSON only. No markdown, no code fences, no extra text.\n"
        "Rules:\n"
        "- Derive ALL fields from the actual content. Do not use placeholder or generic values.\n"
        "- tags: up to 15 items, lowercase kebab-case (a-z0-9 and hyphens). Extract real topics, entities, and document themes from the content (e.g. data-privacy, audit-requirements, vendor-sla).\n"
        "- taxonomy_suggestions: REQUIRED. Fill domains, rule_types, and applies_to from the document (e.g. domains: [\"compliance\", \"legal\"], rule_types: [\"policy\"], applies_to: [\"employees\", \"contractors\"]). Use short kebab-case labels.\n"
        "- doc_type: one short label from content (e.g. policy, template, sla, pricing, security, contract, guideline).\n"
        "- title <= 120 chars, description 30-350 chars, both summarizing the document.\n"
    )

    user = {"schema_hint": schema_hint, "content_sample": context}

    resp = client.chat.completions.create(
        model=model,
        temperature=0,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user)},
        ],
    )

    raw = (resp.choices[0].message.content or "").strip()
    # Strip markdown code block if present (e.g. ```json ... ```)
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```\s*$", "", raw)
    data = json.loads(raw)

    data["document_id"] = document_id
    filename_str = str(filename) if filename is not None else "document"
    data["title"] = str(data.get("title", filename_str.replace("_", " ")))[:120].strip()
    data["description"] = str(data.get("description", ""))[:350].strip()
    data["doc_type"] = str(data.get("doc_type", "other")).strip()
    # Accept tags from "tags" or "tag_list"; no placeholder fill — only real tags
    raw_tags = data.get("tags") or data.get("tag_list") or []
    data["tags"] = clamp_unique_kebab(list(raw_tags), 15)

    tx = data.get("taxonomy_suggestions", {}) or data.get("taxonomy") or {}
    data["taxonomy_suggestions"] = {
        "domains": [kebab(x) for x in tx.get("domains", []) if kebab(x)],
        "rule_types": [kebab(x) for x in tx.get("rule_types", []) if kebab(x)],
        "applies_to": [kebab(x) for x in tx.get("applies_to", []) if kebab(x)],
    }
    if not data["tags"] or not any(data["taxonomy_suggestions"].values()):
        logger.warning(
            "GPT metadata sparse for document_id=%s: tags=%s taxonomy_keys=%s",
            document_id,
            len(data["tags"]),
            {k: len(v) for k, v in data["taxonomy_suggestions"].items()},
        )
    return data


def chunks_list_to_dict_format(chunks: list[str]) -> list[dict[str, Any]]:
    """Convert list of chunk strings to [{chunk_index, page, section, text}, ...]."""
    return [
        {
            "chunk_index": i + 1,
            "page": 1,
            "section": "",
            "text": (c if isinstance(c, str) else str(c)).strip(),
        }
        for i, c in enumerate(chunks)
    ]


def generate_doc_metadata(
    document_id: str,
    filename: str,
    chunks: list[str],
    max_chunks_for_gpt: int = 12,
) -> dict[str, Any]:
    """
    Sample chunks, build context, call GPT, return normalized metadata dict.
    chunks: list of chunk text strings (as stored in document_chunks.content JSON).
    """
    if not chunks:
        raise ValueError("No chunks provided")
    chunks_dict = chunks_list_to_dict_format(chunks)
    sampled = sample_chunks(chunks_dict, max_chunks=max_chunks_for_gpt)
    context = build_context(filename, sampled)
    return gpt_doc_metadata(document_id, filename, context)
