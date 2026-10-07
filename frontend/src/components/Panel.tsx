import type { ReactNode } from 'react';

export default function Panel({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <section className="panel">
      <h3>{title}</h3>
      {children}
    </section>
  );
}
