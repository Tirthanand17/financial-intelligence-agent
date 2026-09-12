import re

from app.storage.vector_store import search_chunks


WORD_RE = re.compile(r"[A-Za-z0-9%₹$._-]+")
# Source line boundaries are meaningful for HTML tables/rate lists and many PDFs,
# so treat them as answer-unit boundaries in addition to sentence punctuation.
SENTENCE_RE = re.compile(r"(?:(?<=[.!?])\s+|\n+)")
# Capture simple financial key/value facts even when an HTML page has been
# flattened into a long navigation-heavy text block.
STRUCTURED_VALUE_RE = re.compile(
    r"(?P<label>[A-Za-z][A-Za-z0-9 /&().,'’\-]{2,90}?)\s*:\s*"
    r"(?P<value>(?:₹|\$|€)?\s*[-+]?\d[\d,.]*"
    r"(?:\s*(?:-|–|to)\s*[-+]?\d[\d,.]*)?"
    r"\s*(?:%|bps|basis points|crore|lakh|million|billion|trillion)?)",
    re.IGNORECASE,
)


def _keywords(text: str) -> set[str]:
    stop = {
        "the", "a", "an", "and", "or", "of", "to", "in", "for", "on", "is", "are",
        "was", "were", "what", "why", "how", "when", "which", "with", "from", "by",
        "shown", "show", "website", "site",
    }
    return {
        token.lower()
        for token in WORD_RE.findall(text)
        if len(token) > 2 and token.lower() not in stop
    }


def _best_label_suffix(label: str, question_terms: set[str]) -> tuple[str, int]:
    """Return the shortest useful label suffix with the strongest query overlap."""
    words = WORD_RE.findall(label)
    if not words:
        return label.strip(), 0

    best_words = words[-8:]
    best_overlap = len(question_terms & {word.lower() for word in best_words})

    for start in range(len(words)):
        suffix = words[start:]
        suffix_terms = {word.lower() for word in suffix}
        overlap = len(question_terms & suffix_terms)
        if overlap > best_overlap or (overlap == best_overlap and overlap > 0 and len(suffix) < len(best_words)):
            best_words = suffix
            best_overlap = overlap

    return " ".join(best_words), best_overlap


def _structured_value_answer(
    question_terms: set[str], matches: list[dict[str, object]]
) -> str | None:
    candidates: list[tuple[int, float, int, str]] = []

    for evidence_index, match in enumerate(matches, start=1):
        text = str(match.get("text", ""))
        retrieval_score = float(match.get("score", 0.0))

        for found in STRUCTURED_VALUE_RE.finditer(text):
            label, overlap = _best_label_suffix(found.group("label"), question_terms)
            if question_terms and overlap == 0:
                continue

            value = " ".join(found.group("value").split())
            answer = f"{label} : {value} [{evidence_index}]"
            # Prefer stronger lexical overlap first, then vector relevance, then
            # shorter labels so navigation text does not drown out the metric.
            candidates.append((overlap, retrieval_score, -len(label), answer))

    if not candidates:
        return None

    candidates.sort(reverse=True)
    return candidates[0][3]


def _extractive_answer(question: str, matches: list[dict[str, object]]) -> str:
    question_terms = _keywords(question)

    structured_answer = _structured_value_answer(question_terms, matches)
    if structured_answer:
        return structured_answer

    candidates: list[tuple[int, float, str, int]] = []

    for evidence_index, match in enumerate(matches, start=1):
        text = str(match.get("text", ""))
        score = float(match.get("score", 0.0))
        for sentence in SENTENCE_RE.split(text):
            sentence = sentence.strip()
            if len(sentence) < 12:
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
