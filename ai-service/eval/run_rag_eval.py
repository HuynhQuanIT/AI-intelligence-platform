"""Chạy bộ kiểm thử chất lượng truy xuất RAG.

    python -m eval.run_rag_eval                       # đo với cấu hình hiện tại
    python -m eval.run_rag_eval --compare off,heuristic --json out.json --summary $GITHUB_STEP_SUMMARY

Nạp bộ tài liệu mẫu vào DB, hỏi từng câu bằng đúng hàm truy xuất của chatbot rồi tính:
  hit@1 / hit@4  tỉ lệ câu có đoạn đúng tài liệu ở top 1 / top 4
  MRR            trung bình 1/vị trí của đoạn đúng đầu tiên (1.0 = luôn đứng đầu)
  fact_recall    tỉ lệ câu mà ngữ cảnh lấy về thực sự chứa dữ kiện cần trả lời
  rejection      với câu ngoài phạm vi: tỉ lệ không trả nguồn nào (chatbot nên nói "không biết")
Tài liệu mẫu được cô lập (viewer.only_docs) và luôn bị xóa khi xong, không ảnh hưởng dữ liệu thật.
Nhóm "semantic" (hỏi diễn đạt khác) chỉ đo khi bật embeddings (LLM_PROVIDER=gemini + GEMINI_API_KEY).
Exit code 1 nếu có chỉ số dưới ngưỡng trong rag_eval_data.json.
"""
import argparse
import json
import sys
from pathlib import Path

DATA = Path(__file__).with_name("rag_eval_data.json")
LIMIT = 4


def load():
    return json.loads(DATA.read_text(encoding="utf-8"))


def _round(x):
    return None if x is None else round(x, 3)


def run_eval(reranker="heuristic", data=None):
    from app.rag import documents, embeddings
    from app.rag.access import ADMIN
    from app.rag.retrieval import retrieve_ex
    from app.rag.text import normalize_text

    data = data or load()
    ids, by_title = [], {}
    try:
        for doc in data["documents"]:
            res = documents.add_document(doc["title"], doc["content"])
            ids.append(res["id"] if "id" in res else res["document_id"])
            by_title[doc["title"]] = ids[-1]
        viewer = {**ADMIN, "only_docs": ids}
        use_semantic = embeddings.enabled()

        rows = []
        for item in data["questions"]:
            tier = item["tier"]
            if tier == "semantic" and not use_semantic:
                continue
            hits, info = retrieve_ex(item["q"], LIMIT, viewer, rerank=reranker)
            row = {"q": item["q"], "tier": tier, "n": len(hits), "mode": info["mode"]}
            if tier == "negative":
                row["rejected"] = len(hits) == 0
            else:
                target = by_title[item["doc"]]
                rank = next((n + 1 for n, h in enumerate(hits) if h["document_id"] == target), None)
                fact = normalize_text(item["fact"])
                row.update(
                    rank=rank,
                    fact=any(fact in normalize_text(h["content"]) for h in hits),
                    top=[h["title"] for h in hits[:2]],
                )
            rows.append(row)
    finally:
        for did in ids:
            documents.delete_document(did)

    metrics = {}
    for tier in ("lexical", "semantic"):
        part = [r for r in rows if r["tier"] == tier]
        if not part:
            metrics[tier] = None if tier == "lexical" else "skipped"
            continue
        ranks = [r["rank"] for r in part]
        metrics[tier] = {
            "n": len(part),
            "hit@1": _round(sum(1 for k in ranks if k == 1) / len(part)),
            "hit@4": _round(sum(1 for k in ranks if k) / len(part)),
            "mrr": _round(sum(1 / k for k in ranks if k) / len(part)),
            "fact_recall": _round(sum(1 for r in part if r["fact"]) / len(part)),
        }
    neg = [r for r in rows if r["tier"] == "negative"]
    metrics["negative"] = {"n": len(neg), "rejection": _round(sum(r["rejected"] for r in neg) / len(neg))} if neg else None
    return {"reranker": reranker, "mode": rows[0]["mode"] if rows else "", "metrics": metrics, "rows": rows}


def check(result, thresholds):
    """Danh sách chỉ số dưới ngưỡng (rỗng = đạt)."""
    failures = []
    for tier, limits in thresholds.items():
        m = result["metrics"].get(tier)
        if not isinstance(m, dict):
            continue
        for key, minimum in limits.items():
            if m.get(key) is not None and m[key] < minimum:
                failures.append(f"{tier}.{key} = {m[key]} < {minimum}")
    return failures


def markdown(results, thresholds):
    lines = ["## Chất lượng truy xuất RAG", "",
             "| Reranker | Nhóm | Số câu | hit@1 | hit@4 | MRR | fact_recall | rejection |",
             "|---|---|---|---|---|---|---|---|"]
    for res in results:
        for tier in ("lexical", "semantic", "negative"):
            m = res["metrics"].get(tier)
            if m == "skipped":
                lines.append(f"| {res['reranker']} | {tier} | - | bỏ qua (cần embeddings) | | | | |")
            elif isinstance(m, dict):
                lines.append(
                    f"| {res['reranker']} | {tier} | {m['n']} | {m.get('hit@1', '')} | {m.get('hit@4', '')} | "
                    f"{m.get('mrr', '')} | {m.get('fact_recall', '')} | {m.get('rejection', '')} |")
    for res in results:
        bad = [r for r in res["rows"] if r["tier"] != "negative" and not r.get("rank") or
               r["tier"] == "negative" and not r.get("rejected")]
        if bad:
            lines += ["", f"**Câu sai ({res['reranker']}):**"]
            lines += [f"- ({r['tier']}) {r['q']}" for r in bad]
    lines += ["", "Ngưỡng: " + json.dumps(thresholds, ensure_ascii=False)]
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--compare", default="", help="danh sách reranker, vd off,heuristic (mặc định: cấu hình hiện tại)")
    ap.add_argument("--json", help="ghi kết quả đầy đủ ra file JSON")
    ap.add_argument("--summary", help="ghi thêm bảng markdown vào file (vd $GITHUB_STEP_SUMMARY)")
    args = ap.parse_args(argv)

    from app.core.db import init_pool
    from app.rag import documents
    from app.rag import rerank as rr

    init_pool()
    documents.ensure_schema()
    names = [n.strip() for n in args.compare.split(",") if n.strip()] or [rr.mode()]
    data = load()
    results = [run_eval(n, data) for n in names]
    thresholds = data["thresholds"]
    table = markdown(results, thresholds)
    print(table)
    if args.json:
        Path(args.json).write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as f:
            f.write(table)
    # Ngưỡng áp dụng cho cấu hình mặc định (reranker cuối danh sách --compare, thường là heuristic).
    failures = check(results[-1], thresholds)
    for f in failures:
        print("FAIL:", f)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
