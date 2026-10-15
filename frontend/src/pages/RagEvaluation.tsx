import { useEffect, useState } from 'react';
import { Play, Plus, Trash2 } from 'lucide-react';
import { api } from '../api/client';
import Panel from '../components/Panel';
import '../components/extras.css';

type Tier = 'lexical' | 'semantic' | 'negative';
type Q = { q: string; tier: Tier; doc: string; fact: string };
type Row = { q: string; tier: Tier; n: number; sim?: number | null; rank?: number | null; fact?: boolean; rejected?: boolean; top?: string[] };
type Metrics = { n: number; 'hit@1'?: number; 'hit@4'?: number; mrr?: number; fact_recall?: number; rejection?: number };
type Result = {
  reranker: string;
  mode: string;
  similarity?: { min_relevant: number | null; max_irrelevant: number | null }; metrics: Record<string, Metrics | 'skipped' | null>; rows: Row[] };
type Report = {
  results: Result[];
  thresholds: Record<string, Record<string, number>>;
  failures: string[];
  semantic_enabled: boolean;
  min_top_similarity?: number;
};
type DocLite = { id: string; title: string; status: string };

const KEY = 'aip-rag-eval-questions';
const TIERS: { id: Tier; label: string }[] = [
  { id: 'lexical', label: 'Gần từ trong tài liệu' },
  { id: 'semantic', label: 'Diễn đạt khác (cần Gemini)' },
  { id: 'negative', label: 'Ngoài phạm vi' },
];
const blank = (): Q => ({ q: '', tier: 'lexical', doc: '', fact: '' });

function load(): Q[] {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) || '[]');
    if (Array.isArray(saved) && saved.length) return saved;
  } catch {
    /* trình duyệt chặn localStorage: bắt đầu từ bảng trống */
  }
  return [blank()];
}

const fmt = (v?: number) => (v == null ? '' : v.toFixed(2));

// Gợi ý ngưỡng MIN_TOP_SIMILARITY từ chính dữ liệu vừa đo (chỉ khi đã bật embeddings).
function Calibration({ report }: { report: Report }) {
  const sim = report.results[report.results.length - 1]?.similarity;
  if (!report.semantic_enabled || !sim || sim.min_relevant == null || sim.max_irrelevant == null) return null;
  const cur = report.min_top_similarity;
  // So sánh theo số làm tròn 2 chữ số như đang hiển thị, tránh báo "tách nhau" khi hai số trông bằng nhau.
  const separable = Math.round(sim.max_irrelevant * 100) < Math.round(sim.min_relevant * 100);
  const mid = ((sim.max_irrelevant + sim.min_relevant) / 2).toFixed(2);
  return (
    <p className="muted">
      Độ giống (cosine) của câu đúng thấp nhất: <b>{sim.min_relevant.toFixed(2)}</b> · của câu ngoài phạm vi cao nhất:{' '}
      <b>{sim.max_irrelevant.toFixed(2)}</b> · ngưỡng hiện tại MIN_TOP_SIMILARITY = <b>{cur}</b>.{' '}
      {separable
        ? `Hai nhóm tách nhau: thử đặt MIN_TOP_SIMILARITY=${mid} trong file .env rồi chạy lại.`
        : 'Hai nhóm chạm hoặc chồng lên nhau: chỉ chỉnh ngưỡng sẽ không tách hẳn được. Đừng đổi ngưỡng theo số này; câu ngoài phạm vi sát nhất có thể là câu cùng chủ đề với tài liệu (không hẳn là lỗi).'}
    </p>
  );
}

// Admin nhập câu hỏi thật, chọn tài liệu đúng, bấm chạy để xem chatbot tìm tài liệu chính xác đến đâu.
export default function RagEvaluation({ setErr }: { setErr: (m: string) => void }) {
  const [questions, setQuestions] = useState<Q[]>(load);
  const [docs, setDocs] = useState<DocLite[]>([]);
  const [compare, setCompare] = useState(false);
  const [running, setRunning] = useState(false);
  const [report, setReport] = useState<Report | null>(null);
  const [importing, setImporting] = useState(false);
  const [importText, setImportText] = useState('');

  useEffect(() => {
    api('/documents')
      .then((list: DocLite[]) => setDocs(list.filter((d) => d.status === 'processed')))
      .catch((e: any) => setErr('Không tải được danh sách tài liệu: ' + e.message));
  }, []);

  useEffect(() => {
    try {
      localStorage.setItem(KEY, JSON.stringify(questions));
    } catch {
      /* bỏ qua */
    }
  }, [questions]);

  const update = (i: number, patch: Partial<Q>) =>
    setQuestions((qs) => qs.map((item, k) => (k === i ? { ...item, ...patch } : item)));

  const run = async () => {
    const filled = questions.filter((item) => item.q.trim());
    if (!filled.length) return setErr('Hãy nhập ít nhất một câu hỏi.');
    setRunning(true);
    setErr('');
    setReport(null);
    try {
      const body = filled.map((item) => ({
        q: item.q.trim(),
        tier: item.tier,
        doc: item.tier === 'negative' ? null : item.doc || null,
        fact: item.tier === 'negative' ? null : item.fact.trim() || null,
      }));
      setReport(await api('/rag-eval', { method: 'POST', body: JSON.stringify({ questions: body, compare }) }));
    } catch (e: any) {
      setErr('Không chạy được phép đo: ' + e.message);
    } finally {
      setRunning(false);
    }
  };

  const doImport = () => {
    try {
      const parsed = JSON.parse(importText);
      const list = Array.isArray(parsed) ? parsed : parsed.questions;
      if (!Array.isArray(list) || !list.length) throw new Error('không có mục "questions"');
      setQuestions(
        list.map((x: any) => ({
          q: String(x.q ?? ''),
          tier: (['lexical', 'semantic', 'negative'].includes(x.tier) ? x.tier : 'lexical') as Tier,
          doc: x.doc ?? '',
          fact: x.fact ?? '',
        })),
      );
      setImporting(false);
      setImportText('');
    } catch (e: any) {
      setErr('JSON không hợp lệ: ' + e.message);
    }
  };

  const wrong = (r: Row) => (r.tier === 'negative' ? !r.rejected : !r.rank);

  return (
    <>
      <Panel title="Bộ câu hỏi thật">
        <p className="muted">
          Mỗi câu: nhập câu hỏi như người dùng sẽ gõ, chọn tài liệu mà câu trả lời đúng phải nằm trong đó, và dán một cụm chữ
          NGUYÊN VĂN trong tài liệu đó. Với câu "Ngoài phạm vi" chatbot nên từ chối nên không cần chọn tài liệu. Bộ câu hỏi được
          nhớ trên trình duyệt này.
        </p>
        {questions.map((item, i) => (
          <div className="rq-row" key={i}>
            <input
              aria-label={`Câu hỏi ${i + 1}`}
              placeholder="Câu hỏi"
              value={item.q}
              onChange={(e) => update(i, { q: e.target.value })}
            />
            <select aria-label={`Loại câu ${i + 1}`} value={item.tier} onChange={(e) => update(i, { tier: e.target.value as Tier })}>
              {TIERS.map((t) => (
                <option key={t.id} value={t.id}>{t.label}</option>
              ))}
            </select>
            <select
              aria-label={`Tài liệu câu ${i + 1}`}
              value={item.doc}
              disabled={item.tier === 'negative'}
              onChange={(e) => update(i, { doc: e.target.value })}
            >
              <option value="">— chọn tài liệu —</option>
              {docs.map((d) => (
                <option key={d.id} value={d.title}>{d.title}</option>
              ))}
            </select>
            <input
              aria-label={`Cụm chữ nguyên văn câu ${i + 1}`}
              placeholder="Cụm chữ nguyên văn trong tài liệu"
              value={item.fact}
              disabled={item.tier === 'negative'}
              onChange={(e) => update(i, { fact: e.target.value })}
            />
            <button
              type="button"
              className="icon-btn"
              aria-label={`Xóa câu ${i + 1}`}
              onClick={() => setQuestions((qs) => (qs.length > 1 ? qs.filter((_, k) => k !== i) : [blank()]))}
            >
              <Trash2 size={15} />
            </button>
          </div>
        ))}

        <div className="rq-actions">
          <button type="button" className="secondary" onClick={() => setQuestions((qs) => [...qs, blank()])}>
            <Plus size={14} /> Thêm câu hỏi
          </button>
          <button type="button" className="secondary" onClick={() => setImporting((v) => !v)}>Nhập từ JSON</button>
          <label className="rq-compare">
            <input type="checkbox" checked={compare} onChange={(e) => setCompare(e.target.checked)} />
            So sánh reranker off và heuristic
          </label>
          <button type="button" className="rq-run" disabled={running} onClick={run}>
            <Play size={14} /> {running ? 'Đang đo…' : 'Chạy đo'}
          </button>
        </div>

        {importing && (
          <div className="rq-import">
            <textarea
              aria-label="JSON bộ câu hỏi"
              rows={6}
              placeholder='{"questions":[{"q":"...","doc":"Tên tài liệu","fact":"cụm chữ","tier":"lexical"}]}'
              value={importText}
              onChange={(e) => setImportText(e.target.value)}
            />
            <button type="button" onClick={doImport}>Nạp vào bảng</button>
          </div>
        )}
      </Panel>

      {report && (
        <Panel title="Kết quả">
          {!report.semantic_enabled && (
            <p className="muted">
              Chưa bật Gemini (LLM_PROVIDER=gemini + GEMINI_API_KEY) nên nhóm "Diễn đạt khác" bị bỏ qua, và cách tìm đang chỉ dựa trên từ khóa.
            </p>
          )}
          <p className={report.failures.length ? 'rq-bad' : 'rq-ok'}>
            {report.failures.length
              ? 'Chưa đạt ngưỡng: ' + report.failures.join('; ')
              : 'Đạt tất cả ngưỡng đề ra.'}
          </p>
          <Calibration report={report} />
          <div className="rq-scroll">
            <table className="rq-table">
              <thead>
                <tr>
                  <th>Reranker</th><th>Nhóm</th><th>Số câu</th><th>hit@1</th><th>hit@4</th><th>MRR</th><th>fact_recall</th><th>rejection</th>
                </tr>
              </thead>
              <tbody>
                {report.results.flatMap((res) =>
                  (['lexical', 'semantic', 'negative'] as const).map((tier) => {
                    const m = res.metrics[tier];
                    if (!m) return null;
                    if (m === 'skipped')
                      return (
                        <tr key={res.reranker + tier}>
                          <td>{res.reranker}</td><td>{tier}</td><td colSpan={6} className="muted">bỏ qua (cần embeddings)</td>
                        </tr>
                      );
                    return (
                      <tr key={res.reranker + tier}>
                        <td>{res.reranker}</td><td>{tier}</td><td>{m.n}</td><td>{fmt(m['hit@1'])}</td><td>{fmt(m['hit@4'])}</td>
                        <td>{fmt(m.mrr)}</td><td>{fmt(m.fact_recall)}</td><td>{fmt(m.rejection)}</td>
                      </tr>
                    );
                  }),
                )}
              </tbody>
            </table>
          </div>
          <small className="muted">
            hit@4: tài liệu đúng nằm trong 4 nguồn đầu · MRR: càng gần 1 càng được xếp cao · fact_recall: đoạn tìm được có chứa cụm chữ
            cần thiết · rejection: tỉ lệ câu ngoài phạm vi bị từ chối đúng. Ngưỡng:{' '}
            {Object.entries(report.thresholds)
              .map(([t, v]) => `${t} ${Object.entries(v).map(([k, x]) => `${k} ≥ ${x}`).join(', ')}`)
              .join(' · ')}
          </small>

          {report.results.map((res) => {
            const bad = res.rows.filter(wrong);
            return (
              <div key={res.reranker} className="rq-wrong">
                <h4>Câu sai ({res.reranker}): {bad.length}/{res.rows.length}</h4>
                {!bad.length && <p className="muted">Không có câu nào sai.</p>}
                {bad.map((r, i) => (
                  <p key={i}>
                    <b>{r.q}</b> <small className="muted">({r.tier})</small>
                    <br />
                    <small className="muted">
                      {r.tier === 'negative'
                        ? `Chatbot vẫn trả ${r.n} nguồn lẽ ra phải từ chối.`
                        : `Không thấy tài liệu đúng trong top 4. Đang trả: ${r.top?.length ? r.top.join(', ') : 'không nguồn nào'}.`}
                      {r.sim != null && ` Độ giống cao nhất: ${r.sim.toFixed(2)}.`}
                    </small>
                  </p>
                ))}
              </div>
            );
          })}
        </Panel>
      )}
    </>
  );
}
