"""Test openai_client and search_answer services (GPT chat client + RAG answer from chunks)."""
import os
import sys

# Run from backend/ so app package and .env are found
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, BACKEND_ROOT)
os.chdir(BACKEND_ROOT)

from app.services.openai_client import get_chat_client
from app.services.search_answer import answer_from_chunks


def test_openai_client():
    """Test get_chat_client() and a single chat completion."""
    print("\n[1] openai_client — get_chat_client() + chat.completions.create()\n")
    client, model = get_chat_client()
    assert client is not None, "get_chat_client() should return a client"
    assert model, "get_chat_client() should return a non-empty model name"
    print(f"  Model: {model}")

    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "Reply in one short sentence: What is 2+2?"}],
        max_tokens=64,
    )
    content = (resp.choices[0].message.content or "").strip()
    assert content, "Completion should return non-empty content"
    print(f"  Response: {content[:200]}")
    print("  OK")
    return True


def test_search_answer_empty_chunks():
    """Test answer_from_chunks with no chunks returns fallback message."""
    print("\n[2] search_answer — answer_from_chunks(question, [])\n")
    question = "What is the deadline?"
    answer, topic = answer_from_chunks(question, [])
    assert "No relevant passages" in answer or "rephrasing" in answer.lower()
    assert topic is None
    print(f"  Answer: {answer[:150]}...")
    print("  OK")
    return True


def test_search_answer_with_chunks():
    """Test answer_from_chunks with mock chunks (real GPT call)."""
    print("\n[3] search_answer — answer_from_chunks(question, chunks)\n")
    question = "What is the proposal deadline?"
    chunks = [
        {
            "content": "The proposal submission deadline is March 15, 2025. Late submissions will not be accepted.",
            "filename": "RFP_terms.pdf",
            "score": 0.92,
        },
        {
            "content": "Budget must not exceed $100,000. Payment terms are Net 30.",
            "filename": "budget.docx",
            "score": 0.75,
        },
    ]
    answer, topic = answer_from_chunks(question, chunks)
    assert answer, "Answer should be non-empty"
    # Answer should reflect passage content (deadline / March / citation)
    assert (
        "deadline" in answer.lower() or "march" in answer.lower() or "15" in answer or "[1]" in answer
    ), "Answer should use passage content"
    print(f"  Answer: {answer[:300]}...")
    print("  OK")
    return True


if __name__ == "__main__":
    print("Testing openai_client + search_answer (uses backend/.env)")
    ok = 0
    try:
        ok += test_openai_client()
    except Exception as e:
        print(f"  FAIL: {e}")
        import traceback
        traceback.print_exc()

    try:
        ok += test_search_answer_empty_chunks()
    except Exception as e:
        print(f"  FAIL: {e}")
        import traceback
        traceback.print_exc()

    try:
        ok += test_search_answer_with_chunks()
    except Exception as e:
        print(f"  FAIL: {e}")
        import traceback
        traceback.print_exc()

    print(f"\nPassed: {ok}/3")
    sys.exit(0 if ok == 3 else 1)
