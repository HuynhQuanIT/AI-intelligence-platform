import { Fragment, type ReactNode } from 'react';

// Trình dựng markdown tối giản, chỉ tạo phần tử React (không dùng innerHTML) nên
// không có đường XSS từ nội dung model trả về.

function inline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*\s][^*]*\*)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const t = m[0];
    if (t.startsWith('`')) out.push(<code key={i++}>{t.slice(1, -1)}</code>);
    else if (t.startsWith('**')) out.push(<strong key={i++}>{inline(t.slice(2, -2))}</strong>);
    else out.push(<em key={i++}>{inline(t.slice(1, -1))}</em>);
    last = m.index + t.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export default function Markdown({ text }: { text: string }) {
  const lines = text.replace(/\r\n/g, '\n').split('\n');
  const blocks: ReactNode[] = [];
  let i = 0;
  let key = 0;

  const isBullet = (l: string) => /^\s*[-*•]\s+/.test(l);
  const isNumber = (l: string) => /^\s*\d+[.)]\s+/.test(l);

  while (i < lines.length) {
    const line = lines[i];

    if (!line.trim()) { i++; continue; }

    if (line.trim().startsWith('```')) {
      const code: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith('```')) code.push(lines[i++]);
      i++;
      blocks.push(<pre key={key++}><code>{code.join('\n')}</code></pre>);
      continue;
    }

    const h = /^(#{1,4})\s+(.*)$/.exec(line);
    if (h) {
      blocks.push(<p key={key++} className="md-heading"><strong>{inline(h[2])}</strong></p>);
      i++;
      continue;
    }

    if (isBullet(line) || isNumber(line)) {
      const ordered = isNumber(line);
      const items: string[] = [];
      while (i < lines.length && (ordered ? isNumber(lines[i]) : isBullet(lines[i]))) {
        items.push(lines[i].replace(/^\s*(?:[-*•]|\d+[.)])\s+/, ''));
        i++;
      }
      const li = items.map((t, n) => <li key={n}>{inline(t)}</li>);
      blocks.push(ordered ? <ol key={key++}>{li}</ol> : <ul key={key++}>{li}</ul>);
      continue;
    }

    const para: string[] = [];
    while (
      i < lines.length && lines[i].trim() &&
      !lines[i].trim().startsWith('```') && !/^#{1,4}\s/.test(lines[i]) &&
      !isBullet(lines[i]) && !isNumber(lines[i])
    ) para.push(lines[i++]);
    blocks.push(
      <p key={key++}>
        {para.map((t, n) => (
          <Fragment key={n}>{n > 0 && <br />}{inline(t)}</Fragment>
        ))}
      </p>,
    );
  }

  return <div className="markdown">{blocks}</div>;
}