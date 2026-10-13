import { useEffect, useState } from 'react';
import { MessageSquareText, ThumbsDown, ThumbsUp } from 'lucide-react';
import { api } from '../api/client';
import Panel from '../components/Panel';
import Stat from '../components/Stat';
import '../components/extras.css';
import type { FeedbackSummary } from '../types';

const pct = (v: number | null) => (v == null ? '—' : Math.round(v * 100) + '%');

// Tổng hợp đánh giá 👍/👎 và danh sách câu trả lời bị 👎 để biết chatbot cần sửa ở đâu.
export default function Feedback({ setErr }: { setErr: (m: string) => void }) {
  const [data, setData] = useState<FeedbackSummary | null>(null);

  useEffect(() => {
    api('/feedback/summary').then(setData).catch((e: any) => setErr('Không tải được thống kê đánh giá: ' + e.message));
  }, []);

  if (!data) return <p className="muted">Đang tải…</p>;

  return (
    <>
      <div className="fb-stats">
        <Stat icon={ThumbsUp} label="Hài lòng (👍)" value={data.up} />
        <Stat icon={ThumbsDown} label="Chưa tốt (👎)" value={data.down} />
        <Stat icon={ThumbsUp} label="Tỉ lệ hài lòng" value={pct(data.satisfaction)} />
        <Stat icon={MessageSquareText} label="Tỉ lệ câu có đánh giá" value={pct(data.rating_rate)} />
      </div>

      <Panel title="Câu trả lời bị 👎 gần đây">
        {!data.recent_down.length && <p className="muted">Chưa có câu trả lời nào bị đánh giá chưa tốt.</p>}
        {data.recent_down.map((item) => (
          <div className="fb-item" key={item.message_id}>
            <small className="muted">{item.user} · {new Date(item.at).toLocaleString()}</small>
            <p><b>Hỏi:</b> {item.question || '(không rõ)'}</p>
            <p><b>Đáp:</b> {item.answer}</p>
            {item.comment && <p><b>Ghi chú của người dùng:</b> {item.comment}</p>}
            <small className="muted">
              Nguồn: {item.sources.length ? item.sources.join(', ') : 'không dùng tài liệu nào'}
            </small>
          </div>
        ))}
      </Panel>
    </>
  );
}
