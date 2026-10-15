"""Đo chất lượng truy xuất RAG trên tài liệu thật (chỉ admin)."""
from fastapi import APIRouter, Depends, HTTPException

from ..rag import embeddings, rerank as rr, retrieval
from ..schemas import RagEval
from .deps import require_admin

router = APIRouter(tags=["rag-eval"])

THRESHOLDS = {
    "lexical": {"hit@4": 0.8, "fact_recall": 0.7},
    "semantic": {"hit@4": 0.7},
    "negative": {"rejection": 0.8},
}


@router.post("/rag-eval")
def run_rag_eval(b: RagEval, _: dict = Depends(require_admin)):
    from eval import run_rag_eval as ev  # gói eval nằm cạnh app (xem Dockerfile)

    for i, item in enumerate(b.questions, 1):
        if item.tier != "negative" and not (item.doc and item.fact):
            raise HTTPException(status_code=422, detail=f"Câu {i}: loại '{item.tier}' cần chọn tài liệu và điền cụm chữ nguyên văn (fact).")

    names = ["off", "heuristic"] if b.compare else [rr.mode()]
    data = {"questions": [i.model_dump() for i in b.questions], "thresholds": THRESHOLDS}
    try:
        results = [ev.run_eval(n, data, live=True) for n in names]
    except ev.EvalError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {
        "results": results,
        "thresholds": THRESHOLDS,
        "failures": ev.check(results[-1], THRESHOLDS),
        "semantic_enabled": embeddings.enabled(),
        "min_top_similarity": retrieval.MIN_TOP_SIMILARITY,
    }
