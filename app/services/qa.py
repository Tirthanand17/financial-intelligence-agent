import re

from app.storage.vector_store import search_chunks


WORD_RE = re.compile(r"[A-Za-z0-9%₹$._-]+")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def _keywords(text: str) -> set[str]:
    stop = {
        "the", "a", "an", "and", "or", "of", "to", "in", "for", "on", "is", "are",
        "was", "were", "what", "why", "how", "when", "which", "with", "from", "by",
    }
    return {token.lower() for token in WORD_RE.findall(text) if len(token) > 2 and token.lower() not in stop}


def _extractive_answer(question: str, matches: list[dict[str, object]]) -> str:
    question_terms = _keywords(question)
    candidates: list[tuple[int, float, str, int]] = []

    for evidence_index, match in enumerate(matches, start=1):
        text = str(match.get("text", ""))
        score = float(match.get("score", 0.0))
        for sentence in SENTENCE_RE.split(text):
            sentence = sentence.strip()
            if len(sentence) < 35:
                continue
            overlap = len(question_terms & _keywords(sentence))
            candidates.append((overlap, score, sentence, evidence_index))

    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    selected: list[str] = []
    seen: set[str] = set()
    for overlap, _score, sentence, evidence_index in candidates:
        if question_terms and overlap == 0:
            continue
        normalized = sentence.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        selected.append(f"{sentence} [{evidence_index}]")
        if len(selected) == 4:
            break

    if selected:
        return " ".join(selected)

    if matches:
        fallback = str(matches[0].get("text", ""))[:1200].strip()
        return f"{fallback} [1]" if fallback else "No answerable text was retrieved."
    return "No indexed evidence was found for this question."


def answer_question(question: str, *, top_k: int = 5, source_id: str | None = None) -> dict[str, object]:
    matches = search_chunks(question, limit=top_k, source_id=source_id)
    answer = _extractive_answer(question, matches)

    evidence: list[dict[str, object]] = []
    for index, match in enumerate(matches, start=1):
        evidence.append(
            {
                "id": index,
                "score": round(float(match.get("score", 0.0)), 4),
                "source_id": match.get("source_id"),
                "source_name": match.get("source_name"),
                "title": match.get("title"),
                "source_url": match.get("source_url"),
                "retrieved_at": match.get("retrieved_at"),
                "authority_level": match.get("authority_level"),
                "chunk_index": match.get("chunk_index"),
                "text": match.get("text"),
            }
        )

    top_score = float(matches[0].get("score", 0.0)) if matches else 0.0
    confidence = "high" if top_score >= 0.70 else "medium" if top_score >= 0.50 else "low"

    return {
        "question": question,
        "answer_mode": "extractive_grounded",
        "answer": answer,
        "confidence": confidence,
        "evidence": evidence,
        "warning": "The answer is limited to retrieved indexed evidence and is not financial advice.",
    }
