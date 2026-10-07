import io
import re
import zipfile

ALLOWED_EXTENSIONS = {".txt", ".md", ".pdf", ".docx"}
MAX_PDF_PAGES = 300
MAX_DOCX_UNZIPPED = 50 * 1024 * 1024  # chống zip bomb


class ExtractError(ValueError):
    """File hợp lệ về đuôi nhưng không đọc được nội dung."""


def extension(filename: str) -> str:
    name = (filename or "").lower()
    dot = name.rfind(".")
    return name[dot:] if dot >= 0 else ""


def _clean(text: str) -> str:
    # PostgreSQL TEXT không chấp nhận ký tự NUL.
    text = text.replace("\x00", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _decode_text(data: bytes) -> str:
    # utf-16 chỉ khi có BOM: không có BOM thì byte bất kỳ đều "giải mã được" thành rác.
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    for encoding in ("utf-8-sig", "cp1258"):
        try:
            return data.decode(encoding)
        except UnicodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _read_pdf(data: bytes) -> str:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise ExtractError("PDF được bảo vệ bằng mật khẩu.")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise ExtractError(f"PDF quá {MAX_PDF_PAGES} trang.")
        pages = [(page.extract_text() or "") for page in reader.pages]
    except ExtractError:
        raise
    except Exception as exc:
        raise ExtractError("Không đọc được file PDF (hỏng hoặc sai định dạng).") from exc

    return "\n\n".join(pages)


def _read_docx(data: bytes) -> str:
    from docx import Document

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if sum(i.file_size for i in archive.infolist()) > MAX_DOCX_UNZIPPED:
                raise ExtractError("File DOCX giải nén quá lớn.")
        document = Document(io.BytesIO(data))
    except ExtractError:
        raise
    except Exception as exc:
        raise ExtractError("Không đọc được file DOCX (hỏng hoặc sai định dạng).") from exc

    blocks = [p.text for p in document.paragraphs if p.text.strip()]
    for table in document.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                blocks.append(" | ".join(cells))
    return "\n\n".join(blocks)


def extract_text(filename: str, data: bytes) -> str:
    ext = extension(filename)

    if ext in (".txt", ".md"):
        text = _decode_text(data)
    elif ext == ".pdf":
        if not data.startswith(b"%PDF"):
            raise ExtractError("Nội dung không phải PDF.")
        text = _read_pdf(data)
    elif ext == ".docx":
        if not data.startswith(b"PK"):
            raise ExtractError("Nội dung không phải DOCX.")
        text = _read_docx(data)
    else:
        raise ExtractError(f"Định dạng {ext or '(không đuôi)'} chưa được hỗ trợ.")

    text = _clean(text)
    if not text:
        raise ExtractError(
            "Không trích xuất được văn bản. Nếu là PDF scan (ảnh) thì cần OCR, hiện chưa hỗ trợ."
        )
    return text
