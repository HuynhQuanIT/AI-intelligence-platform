// Đọc luồng Server-Sent Events (start, step, delta, reset, done, error).

export async function readSse(
  body: ReadableStream<Uint8Array>,
  handle: (event: string, data: any) => void
) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    // Mỗi sự kiện SSE kết thúc bằng một dòng trống.
    let cut: number;
    while ((cut = buffer.indexOf('\n\n')) !== -1) {
      const block = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);

      let event = 'message';
      const dataLines: string[] = [];
      for (const line of block.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim();
        else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim());
      }
      if (dataLines.length) handle(event, JSON.parse(dataLines.join('\n')));
    }
  }
}
