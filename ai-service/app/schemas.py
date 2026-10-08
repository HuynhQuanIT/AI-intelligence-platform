"""Mô hình dữ liệu của request."""
from pydantic import BaseModel, Field


class Doc(BaseModel):
    title: str = Field(min_length=1, max_length=250)
    content: str = Field(min_length=1, max_length=200000)


class Eval(BaseModel):
    question: str
    answer: str
    expected: str = ""


class HistoryItem(BaseModel):
    role: str          # "user" hoặc "ai"
    text: str = Field(max_length=12000)


class Chat(BaseModel):
    message: str = Field(min_length=1, max_length=12000)
    use_rag: bool = True
    model: str | None = None
    history: list[HistoryItem] = Field(default_factory=list, max_length=20)
    # Có conversation_id thì server lưu tin nhắn và lấy lịch sử từ database (bỏ qua history do client gửi).
    conversation_id: str | None = None


class EmailBody(BaseModel):
    email: str = Field(max_length=254)


class OtpBody(BaseModel):
    email: str = Field(max_length=254)
    code: str = Field(max_length=12)


class PasswordBody(BaseModel):
    token: str = Field(max_length=2000)
    password: str = Field(max_length=200)


class ResetBody(PasswordBody):
    pass


class LoginBody(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)


class RoleBody(BaseModel):
    role: str = Field(max_length=20)


class AdminPasswordBody(BaseModel):
    password: str = Field(max_length=200)
