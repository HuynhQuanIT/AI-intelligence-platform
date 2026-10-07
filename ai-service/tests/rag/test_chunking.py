from app.rag.chunking import MAX_CHARS, OVERLAP, split_text


def test_empty_text_gives_no_chunks():
    assert split_text("") == []
    assert split_text("   \n\n  ") == []


def test_short_text_is_one_chunk():
    assert split_text("Xin chào thế giới.") == ["Xin chào thế giới."]


def test_chunks_respect_max_size():
    text = "\n\n".join(f"Đoạn số {i}. " + "nội dung " * 60 for i in range(30))
    chunks = split_text(text)
    assert len(chunks) > 1
    assert all(len(c) <= MAX_CHARS for c in chunks)


def test_long_paragraph_is_split_on_sentence_or_word():
    text = ("Câu dài không xuống dòng " * 200).strip()
    chunks = split_text(text)
    assert len(chunks) > 1
    assert all(len(c) <= MAX_CHARS for c in chunks)


def test_consecutive_chunks_overlap():
    text = "\n\n".join(f"Đoạn {i}: " + "từ khóa riêng " * 40 + f"kết thúc{i}" for i in range(12))
    chunks = split_text(text)
    assert len(chunks) > 2
    for before, after in zip(chunks, chunks[1:]):
        tail = before[-OVERLAP:].split(" ", 1)[-1][:30]
        assert tail in after, "chunk sau phải lặp lại phần cuối của chunk trước"