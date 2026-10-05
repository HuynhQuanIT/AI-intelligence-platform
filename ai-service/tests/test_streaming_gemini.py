"""Luồng Gemini với client giả: kiểm tra streaming thật, vòng công cụ, reset và dự phòng."""
import pytest
from google.genai import types

from app import llm
from conftest import parse_sse

pytestmark = pytest.mark.integration


def chunk(parts, usage=(5, 3)):
    meta = types.GenerateContentResponseUsageMetadata(
        prompt_token_count=usage[0], candidates_token_count=usage[1]
    )
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=parts))],
        usage_metadata=meta,
    )


def text(t):
    return types.Part(text=t)


def call(name, args):
    return types.Part(function_call=types.FunctionCall(name=name, args=args))


@pytest.fixture
def fake_gemini(monkeypatch):
    """Mỗi phần tử của script là một lượt gọi model: list chunk, hoặc Exception để mô phỏng lỗi."""
    script, seen = [], []

    class Models:
        async def generate_content_stream(self, **kwargs):
            seen.append({"messages": len(kwargs["contents"]), "tools": kwargs["config"].tools is not None})
            step = script.pop(0)
            if isinstance(step, Exception):
                raise step

            async def gen():
                for item in step:
                    yield item

            return gen()

    class Aio:
        models = Models()

        async def aclose(self):
            pass

    class FakeClient:
        def __init__(self, api_key=None):
            self.aio = Aio()

    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.setattr(llm.genai, "Client", FakeClient)
    return script, seen


def run(stream_chat, message, use_rag):
    status, _, body = stream_chat({"message": message, "use_rag": use_rag})
    assert status == 200
    return parse_sse(body)


def test_plain_answer_streams_in_pieces(fake_gemini, stream_chat):
    script, _ = fake_gemini
    script[:] = [[chunk([text("Xin ")]), chunk([text("chào ")]), chunk([text("bạn!")], (11, 7))]]

    events = run(stream_chat, "Chào", use_rag=False)

    assert [d["delta"] for n, d in events if n == "delta"] == ["Xin ", "chào ", "bạn!"]
    done = events[-1][1]
    assert done["answer"] == "Xin chào bạn!"
    assert (done["input_tokens"], done["output_tokens"]) == (11, 7)


def test_tool_round_resets_lead_in_and_streams_final_answer(fake_gemini, stream_chat):
    script, seen = fake_gemini
    script[:] = [
        [chunk([text("Để tôi tính... ")]), chunk([call("calculate", {"expression": "12*34"})])],
        [chunk([text("Kết quả ")], (9, 0)), chunk([text("là **408**.")], (9, 4))],
    ]

    events = run(stream_chat, "Tính giúp tôi 12 * 34", use_rag=True)
    names = [n for n, _ in events]

    assert "reset" in names
    assert names.index("reset") > names.index("delta")  # lời dẫn đã hiện rồi mới bị xóa
    after_reset = "".join(d["delta"] for n, d in events[names.index("reset"):] if n == "delta")
    assert after_reset == "Kết quả là **408**."

    done = events[-1][1]
    assert done["answer"] == "Kết quả là **408**."
    assert (done["input_tokens"], done["output_tokens"]) == (14, 7)
    tool_steps = [t for t in done["trace"] if t["step"] == "tool:calculate"]
    assert tool_steps and tool_steps[0]["status"] == "completed"
    assert [s["tools"] for s in seen] == [True, True]


def test_failure_in_tool_loop_falls_back_to_plain_answer(fake_gemini, stream_chat):
    script, _ = fake_gemini
    script[:] = [RuntimeError("boom"), [chunk([text("Trả lời ")]), chunk([text("dự phòng")])]]

    events = run(stream_chat, "Giải thích RAG", use_rag=True)

    done = events[-1][1]
    assert events[-1][0] == "done"
    assert done["answer"] == "Trả lời dự phòng"
    assert any(t["step"] == "tools" and t["status"] == "error" for t in done["trace"])


def test_empty_model_response_becomes_error_event(fake_gemini, stream_chat):
    script, _ = fake_gemini
    script[:] = [[chunk([text("")], (4, 0))]]

    events = run(stream_chat, "Chào", use_rag=False)

    assert events[-1][0] == "error"
    assert "failed" in events[-1][1]["detail"].lower()