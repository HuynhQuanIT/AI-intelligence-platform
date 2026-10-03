import asyncio
from typing import TypedDict

from langgraph.graph import END, StateGraph

from .llm import generate
from .rag import retrieve


class State(TypedDict):
    message: str
    use_rag: bool
    model: str | None
    history: list
    context: list
    answer: str
    trace: list
    input_tokens: int
    output_tokens: int
    selected_model: str


def build():
    async def supervisor(s):
        step = {
            "step": "supervisor",
            "status": "completed",
            "detail": "Request classified",
        }
        return {"trace": s["trace"] + [step]}

    async def knowledge(s):
        # retrieve() dùng DB đồng bộ -> chạy ở thread riêng để không chặn event loop
        if s["use_rag"]:
            docs = await asyncio.to_thread(retrieve, s["message"])
        else:
            docs = []

        step = {
            "step": "knowledge",
            "status": "completed",
            "detail": f"{len(docs)} chunks retrieved",
        }
        return {"context": docs, "trace": s["trace"] + [step]}

    async def analysis(s):
        step = {
            "step": "analysis",
            "status": "completed",
            "detail": "Context prepared",
        }
        return {"trace": s["trace"] + [step]}

    async def response(s):
        ctx = "\n\n".join(
            "Source: " + d["title"] + "\n" + d["content"] for d in s["context"]
        )

        history = s.get("history") or []
        hist = "\n".join(
            ("User: " if h["role"] == "user" else "Assistant: ") + h["text"]
            for h in history
        )

        prompt = (
            "Answer clearly in the user's language.\n"
            "Use the conversation history to understand follow-up questions.\n"
            "Use the retrieved context when it is relevant; "
            "if the question depends on documents and the context is insufficient, say so.\n\n"
            f"Conversation so far:\n{hist or '(none)'}\n\n"
            f"Question: {s['message']}\n"
            f"Context:\n{ctx or '(No retrieved context)'}"
        )

        answer, inp, out, model = await generate(prompt, s["model"])

        step = {
            "step": "response",
            "status": "completed",
            "detail": "Generated with " + model,
        }
        return {
            "answer": answer,
            "input_tokens": inp,
            "output_tokens": out,
            "selected_model": model,
            "trace": s["trace"] + [step],
        }

    g = StateGraph(State)

    for name, fn in [
        ("supervisor", supervisor),
        ("knowledge", knowledge),
        ("analysis", analysis),
        ("response", response),
    ]:
        g.add_node(name, fn)

    g.set_entry_point("supervisor")
    g.add_edge("supervisor", "knowledge")
    g.add_edge("knowledge", "analysis")
    g.add_edge("analysis", "response")
    g.add_edge("response", END)

    return g.compile()


graph = build()