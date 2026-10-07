import type { LucideIcon } from 'lucide-react';

type Props = { icon: LucideIcon; label: string; value: string | number };

export default function Stat({ icon: Icon, label, value }: Props) {
  return (
    <div className="stat">
      <div>
        {label}
        <Icon size={17} />
      </div>

      <strong>{value}</strong>

      <small>Recorded platform metric</small>
    </div>
  );
}
