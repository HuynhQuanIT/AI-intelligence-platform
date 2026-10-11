import type { Quota } from '../types';
import './extras.css';

// Thanh hạn mức tin nhắn trong ngày. limit = null nghĩa là không giới hạn.
export default function QuotaBar({ quota }: { quota?: Quota }) {
  if (!quota) return null;

  if (quota.limit === null) {
    return <p className="quota-text">Hôm nay đã gửi {quota.used} tin nhắn · không giới hạn</p>;
  }

  const percent = Math.min(100, Math.round((quota.used / Math.max(1, quota.limit)) * 100));
  const level = percent >= 100 ? 'full' : percent >= 80 ? 'warn' : 'ok';

  return (
    <div className="quota">
      <div className="quota-track" role="progressbar" aria-valuemin={0} aria-valuemax={quota.limit} aria-valuenow={quota.used}>
        <div className={'quota-fill ' + level} style={{ width: percent + '%' }} />
      </div>
      <p className="quota-text">
        Hôm nay: {quota.used}/{quota.limit} tin nhắn · còn {quota.remaining ?? 0} · làm mới lúc{' '}
        {new Date(quota.resets_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
      </p>
    </div>
  );
}
