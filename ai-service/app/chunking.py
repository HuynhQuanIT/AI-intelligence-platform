import re

MAX_CHARS = 900
OVERLAP = 150


def _hard_split(text, max_chars):
    """Cắt đoạn quá dài: ưu tiên ranh giới câu, sau đó ranh giới từ."""
    parts, current = [], ""
    for sentence in re.split(r"(?<=[.!?。])\s+", text):
        while len(sentence) > max_chars:
            cut = sentence.rfind(" ", 0, max_chars)
            cut = cut if cut > max_chars // 2 else max_chars
            if current:
                parts.append(current)
                current = ""
            parts.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if current and len(current) + 1 + len(sentence) > max_chars:
            parts.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        parts.append(current)
    return parts


def _tail(text, overlap):
    """Lấy ~overlap ký tự cuối, bắt đầu ở ranh giới từ."""
    if overlap <= 0 or len(text) <= overlap:
        return text if overlap > 0 else ""
    tail = text[-overlap:]
    space = tail.find(" ")
    return tail[space + 1:] if 0 <= space < len(tail) - 1 else tail


def split_text(text, max_chars=MAX_CHARS, overlap=OVERLAP):
    """
    Chia văn bản theo đoạn: gộp các đoạn liền nhau đến khi gần đủ max_chars,
    đoạn quá dài thì cắt theo câu. Chunk sau lặp lại ~overlap ký tự cuối
    của chunk trước để không mất ngữ cảnh ở ranh giới.
    """
    text = (text or "").strip()
    if not text:
        return []

    pieces = []
    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = re.sub(r"[ \t]*\n[ \t]*", " ", paragraph).strip()
        if not paragraph:
            continue
        if len(paragraph) <= max_chars:
            pieces.append(paragraph)
        else:
            pieces.extend(_hard_split(paragraph, max_chars))

    chunks, current = [], ""
    for piece in pieces:
        if current and len(current) + 2 + len(piece) > max_chars:
            chunks.append(current)
            seed = _tail(current, overlap)
            current = f"{seed}\n\n{piece}" if seed else piece
            if len(current) > max_chars:  # phần lặp làm chunk vượt trần
                current = piece
        else:
            current = f"{current}\n\n{piece}" if current else piece
    if current:
        chunks.append(current)

    return chunks
