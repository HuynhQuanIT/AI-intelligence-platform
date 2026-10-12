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

type Item = { indent: number; ordered: boolean; num: number; text: string };

const LIST_RE = /^(\s*)(?:([-*•])|(\d+)[.)])\s+(.*)$/;

function parseItem(line: string): Item | null {
  const m = LIST_RE.exec(line);
  if (!m) return null;
  return { indent: m[1].replace(/\t/g, '    ').length, ordered: m[3] !== undefined, num: Number(m[3] ?? 1), text: m[4] };
}

// Dựng danh sách lồng nhau theo mức thụt lề. Mục đánh số giữ đúng số thứ tự (start) nên
// "1. … gạch đầu dòng … 2. …" không bị đánh số lại từ 1 sau mỗi cụm gạch đầu dòng.
function renderList(items: Item[], from: number, keyBase: string): [ReactNode, number] {
  const base = items[from].indent;
  const ordered = items[from].ordered;
  const lis: ReactNode[] = [];
  let pos = from;
  while (pos < items.length && items[pos].indent >= base) {
    if (items[pos].indent === base && items[pos].ordered !== ordered) break;
    const it = items[pos++];
    let nested: ReactNode = null;
    if (pos < items.length && items[pos].indent > base) {
      [nested, pos] = renderList(items, pos, `${keyBase}-${lis.length}`);
    }
    lis.push(<li key={lis.length}>{inline(it.text)}{nested}</li>);
  }
  const list = ordered
    ? <ol key={keyBase} start={items[from].num}>{lis}</ol>
    : <ul key={keyBase}>{lis}</ul>;
  return [list, pos];
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
      // Gom cả khối danh sách, cho phép dòng trống xen giữa nếu sau đó vẫn là mục danh sách.
      const items: Item[] = [];
      while (i < lines.length) {
        const item = parseItem(lines[i]);
        if (item) { items.push(item); i++; continue; }
        if (!lines[i].trim()) {
          let j = i;
          while (j < lines.length && !lines[j].trim()) j++;
          if (j < lines.length && parseItem(lines[j])) { i = j; continue; }
        }
        break;
      }
      // Model hay viết gạch đầu dòng KHÔNG thụt lề ngay dưới mục đánh số: coi đó là mục con của số đó.
      let orderedIndent = -1;
      for (const it of items) {
        if (it.ordered) orderedIndent = it.indent;
        else if (orderedIndent >= 0 && it.indent === orderedIndent) it.indent += 2;
        else if (it.indent < orderedIndent) orderedIndent = -1;
      }
      let pos = 0;
      while (pos < items.length) {
        const [node, next] = renderList(items, pos, `l${key++}`);
        blocks.push(node);
        pos = next;
      }
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