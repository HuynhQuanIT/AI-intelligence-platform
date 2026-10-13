"""Xếp hạng lại (reranking) các đoạn đã truy xuất.

Truy xuất bước 1 (từ khóa / vector) lấy rộng một nhóm ứng viên; bước 2 chấm lại từng ứng viên
bằng nhiều tín hiệu rồi chọn top đưa cho LLM. RERANKER=off|heuristic|llm (mặc định heuristic).
Mọi lỗi của bộ chấm đều quay về thứ tự cũ, không bao giờ làm hỏng câu trả lời.
"""
import json
import logging
import os
import re

from .text import keywords, normalize_text, words

logger = logging.getLogger(__name__)

WINDOW = 12  # số từ tối đa của cửa sổ "gần nhau"


def mode() -> str:
    value = os.getenv("RERANKER", "heuristic").strip().lower()
    return value if value in ("off", "heuristic", "llm") else "heuristic"


def _tokens(text: str) -> list[str]:
    return re.findall(r"\w+", normalize_text(text))


def _bigrams(seq: list[str]) -> set[tuple[str, str]]:
    return set(zip(seq, seq[1:]))


def heuristic_scores(question: str, items: list[dict]) -> list[float]:
    """Điểm 0..1 cho từng ứng viên: phủ từ khóa, cụm từ liền nhau, độ gần, tên tài liệu, điểm gốc."""
    qkeys = keywords(question)
    q_tokens = [t for t in _tokens(question) if t in qkeys]
    q_bigrams = _bigrams(_tokens(question))
    base = [float(i.get("score") or 0) for i in items]
    top = max(base) if base and max(base) > 0 else 1.0
    out = []
    for item, b in zip(items, base):
        tokens = _tokens(item.get("content") or "")
        tset = set(tokens)
        coverage = len(qkeys & tset) / max(1, len(qkeys))
        phrase = len(q_bigrams & _bigrams(tokens)) / max(1, len(q_bigrams))
        # Cửa sổ nhỏ nhất chứa nhiều từ khóa nhất: các từ khóa nằm sát nhau thì đoạn đó "nói về" câu hỏi.
        positions = [(n, t) for n, t in enumerate(tokens) if t in qkeys]
        proximity = 0.0
        if positions and qkeys:
            best = 0
            left = 0
            seen: dict[str, int] = {}
            for right, (pos, tok) in enumerate(positions):
                seen[tok] = seen.get(tok, 0) + 1
                while pos - positions[left][0] > WINDOW:
                    old = positions[left][1]
                    seen[old] -= 1
                    if not seen[old]:
                        del seen[old]
                    left += 1
                best = max(best, len(seen))
            proximity = best / len(qkeys)
        title = len(qkeys & words(item.get("title") or "")) / max(1, len(qkeys))
        score = 0.30 * coverage + 0.25 * phrase + 0.15 * proximity + 0.10 * title + 0.20 * (b / top)
        sim = item.get("similarity")
        if sim is not None:
            score += 0.15 * max(0.0, min(1.0, (float(sim) - 0.5) / 0.4))
        out.append(score)
    return out


def _llm_scores(question: str, items: list[dict]) -> list[float] | None:
    """Nhờ Gemini chấm 0-10 mỗi đoạn. Trả None nếu không dùng được (không key, lỗi, trả sai định dạng)."""
    key = os.getenv("GEMINI_API_KEY")
    if not key or os.getenv("LLM_PROVIDER", "").lower() != "gemini":
        return None
    try:
        from google import genai

        passages = "\n".join(f"[{n}] {(i.get('content') or '')[:700]}" for n, i in enumerate(items))
        prompt = (
            "Chấm mức độ đoạn văn trả lời được câu hỏi, thang 0-10 (0 = không liên quan). "
            'Chỉ trả JSON dạng {"scores":[số,...]} theo đúng thứ tự đoạn.\n'
            f"Câu hỏi: {question}\nCác đoạn:\n{passages}"
        )
        client = genai.Client(api_key=key, http_options={"timeout": 8000})
        resp = client.models.generate_content(
            model=os.getenv("GEMINI_MODEL", "gemini-2.0-flash"), contents=prompt,
            config={"response_mime_type": "application/json"},
        )
        scores = json.loads(resp.text)["scores"]
        if len(scores) != len(items):
            return None
        return [max(0.0, min(10.0, float(s))) / 10 for s in scores]
    except Exception:
        logger.warning("LLM rerank failed; keeping heuristic order", exc_info=True)
        return None


def rerank(question: str, items: list[dict], limit: int, override: str | None = None) -> tuple[list[dict], str]:
    """Trả (top `limit` đã xếp lại, tên cách đã dùng). Không đổi trường score gốc; thêm rerank_score."""
    chosen = override or mode()
    if chosen == "off" or len(items) < 2:
        return items[:limit], "off"
    try:
        scores = heuristic_scores(question, items)
        used = "heuristic"
        if chosen == "llm":
            llm = _llm_scores(question, items)
            if llm is not None:
                scores = [0.6 * l + 0.4 * h for l, h in zip(llm, scores)]
                used = "llm"
    except Exception:
        logger.exception("rerank failed; keeping original order")
        return items[:limit], "off"
    order = sorted(range(len(items)), key=lambda n: (-scores[n], n))  # ổn định khi hòa điểm
    result = []
    for n in order[:limit]:
        item = dict(items[n])
        item["rerank_score"] = round(scores[n], 4)
        result.append(item)
    return result, used
