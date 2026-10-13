"""Bộ kiểm thử chất lượng RAG chạy như một test: tụt dưới ngưỡng thì CI đỏ.
Chi tiết (câu nào sai, so sánh có/không reranking): python -m eval.run_rag_eval --compare off,heuristic"""
import pytest

from eval.run_rag_eval import check, load, run_eval

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def results(client):  # client: dựng DB/app như các test khác
    data = load()
    return {name: run_eval(name, data) for name in ("off", "heuristic")}, data["thresholds"]


def test_dataset_is_big_enough():
    data = load()
    assert len(data["questions"]) >= 30
    assert {q["tier"] for q in data["questions"]} == {"lexical", "semantic", "negative"}


def test_quality_thresholds(results):
    res, thresholds = results
    failures = check(res["heuristic"], thresholds)
    assert not failures, failures


def test_rerank_never_worse_than_no_rerank(results):
    res, _ = results
    off, on = res["off"]["metrics"], res["heuristic"]["metrics"]
    assert on["lexical"]["mrr"] >= off["lexical"]["mrr"]
    assert on["lexical"]["hit@1"] >= off["lexical"]["hit@1"]
    assert on["negative"]["rejection"] >= off["negative"]["rejection"]


def test_eval_documents_are_cleaned_up(results):
    from app.core.db import query
    titles = [d["title"] for d in load()["documents"]]
    assert not query("SELECT 1 FROM documents WHERE title = ANY(%s)", (titles,))
