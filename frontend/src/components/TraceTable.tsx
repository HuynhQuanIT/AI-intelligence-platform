import type { TraceRow } from '../types';

export default function TraceTable({ rows }: { rows: TraceRow[] }) {
  return (
    <div className="tablewrap">
      <table>
        <thead>
          <tr>
            <th>Request ID</th>
            <th>Step</th>
            <th>Status</th>
            <th>Created</th>
          </tr>
        </thead>

        <tbody>
          {rows.map((row) => (
            <tr key={row.id}>
              <td>{String(row.request_id).slice(0, 12)}…</td>
              <td>{row.step}</td>
              <td>
                <em>{row.status}</em>
              </td>
              <td>{new Date(row.created_at).toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
