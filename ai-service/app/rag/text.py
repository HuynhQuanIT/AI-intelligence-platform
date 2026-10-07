"""Chuẩn hóa văn bản và trích từ khóa (dùng chung cho truy xuất và bộ quét bảo mật)."""
import re
import unicodedata


def normalize_text(text: str) -> str:
    """
    Chuẩn hóa chữ thường, bỏ dấu tiếng Việt và loại ký tự đặc biệt.
    Ví dụ:
    'Quy định thử nghiệm' -> 'quy dinh thu nghiem'
    """
    text = (text or "").lower().strip()

    text = unicodedata.normalize("NFD", text)
    text = "".join(
        char for char in text
        if unicodedata.category(char) != "Mn"
    )

    text = text.replace("đ", "d")
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def words(text: str) -> set[str]:
    return set(re.findall(r"\w+", normalize_text(text)))


# Từ chức năng (đã chuẩn hóa, không dấu). Nếu không loại bỏ, câu hỏi như
# "How often is the company car serviced?" khớp từ khóa với gần như mọi chunk
# qua "is", "the", "how"... và đẩy chunk đúng nghĩa ra khỏi top kết quả.
STOPWORDS = {
    # English
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "am",
    "do", "does", "did", "how", "what", "when", "where", "which", "who",
    "whom", "why", "of", "to", "in", "on", "at", "for", "from", "by",
    "with", "and", "or", "not", "it", "its", "this", "that", "these",
    "those", "i", "you", "we", "they", "he", "she", "my", "your", "our",
    "their", "can", "could", "should", "would", "will", "may", "might",
    "about", "as", "if", "so", "than", "then", "there", "has", "have", "had",
    # Vietnamese (không dấu)
    "la", "gi", "va", "cua", "co", "cho", "cac", "nhung", "mot", "nay",
    "duoc", "trong", "khi", "de", "voi", "thi", "ma", "hay", "nhu", "nao",
    "khong", "bi", "o", "tai", "ve", "tu", "den", "da", "se", "dang",
    "rat", "cung", "nhe", "ban", "toi", "minh",
}


def keywords(text: str) -> set[str]:
    """Từ khóa có nghĩa của câu hỏi; nếu toàn từ chức năng thì dùng lại tất cả."""
    all_words = words(text)
    # Số ngắn ("12", "34") khớp bừa vào mọi tài liệu có bảng số liệu nên không dùng làm từ khóa;
    # số dài hơn (năm 2026, mã 404...) vẫn giữ.
    meaningful = {w for w in all_words - STOPWORDS if not (w.isdigit() and len(w) < 3)}
    return meaningful or (all_words - STOPWORDS) or all_words
