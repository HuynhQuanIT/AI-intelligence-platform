import os

import httpx
from google import genai
from google.genai import types


async def _generate_openai(prompt: str, model: str | None = None):
    selected = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    api_key = os.getenv("OPENAI_API_KEY", "").strip()

    if not api_key:
        raise RuntimeError("LLM_PROVIDER=openai but OPENAI_API_KEY is missing.")

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": selected,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
            },
        )
        response.raise_for_status()
        data = response.json()

    answer = data["choices"][0]["message"]["content"]
    usage = data.get("usage", {})

    return (
        answer,
        usage.get("prompt_tokens", 0),
        usage.get("completion_tokens", 0),
        selected,
    )


async def _generate_gemini(prompt: str, model: str | None = None):
    api_key = os.getenv("GEMINI_API_KEY", "").strip()

    if not api_key:
        raise RuntimeError("LLM_PROVIDER=gemini but GEMINI_API_KEY is missing.")

    selected = model or os.getenv("GEMINI_MODEL", "gemini-3.8-flash")

    client = genai.Client(api_key=api_key)

    try:
        response = await client.aio.models.generate_content(
            model=selected,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=float(os.getenv("GEMINI_TEMPERATURE", "0.2")),
                max_output_tokens=int(
                    os.getenv("GEMINI_MAX_OUTPUT_TOKENS", "2048")
                ),
            ),
        )
    finally:
        await client.aio.aclose()

    answer = (response.text or "").strip()

    if not answer:
        raise RuntimeError(
            "Gemini returned an empty response. "
            "Check the model response or safety feedback."
        )

    usage = response.usage_metadata
    input_tokens = getattr(usage, "prompt_token_count", 0) or 0
    output_tokens = getattr(usage, "candidates_token_count", 0) or 0

    return answer, input_tokens, output_tokens, selected


async def generate(prompt: str, model: str | None = None):
    provider = os.getenv("LLM_PROVIDER", "mock").strip().lower()

    if provider == "openai":
        return await _generate_openai(prompt, model)

    if provider == "gemini":
        return await _generate_gemini(prompt, model)

    if provider != "mock":
        raise RuntimeError(f"Unsupported LLM_PROVIDER: {provider}")

    answer = (
        "[DEMO MODE] Request received. Context and task:\n"
        + prompt[-1600:]
        + "\n\nConfigure a hosted LLM provider for real model-generated responses."
    )

    return (
        answer,
        max(1, len(prompt) // 4),
        max(1, len(answer) // 4),
        "mock-local",
    )


def supports_tools() -> bool:
    """Function calling hiện chỉ hỗ trợ Gemini (cần API key)."""
    provider = os.getenv("LLM_PROVIDER", "mock").strip().lower()
    return provider == "gemini" and bool(os.getenv("GEMINI_API_KEY", "").strip())


def _declaration(spec: dict) -> types.FunctionDeclaration:
    kinds = {"string": types.Type.STRING, "integer": types.Type.INTEGER}
    return types.FunctionDeclaration(
        name=spec["name"],
        description=spec["description"],
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                key: types.Schema(type=kinds[kind], description=description)
                for key, (kind, description, _required) in spec["parameters"].items()
            },
            required=[
                key for key, (_k, _d, required) in spec["parameters"].items() if required
            ],
        ),
    )


async def generate_with_tools(
    prompt: str,
    model: str | None,
    specs: list[dict],
    run_tool,
    max_rounds: int = 4,
    max_calls_per_round: int = 3,
):
    """
    Vòng lặp: model -> (gọi công cụ -> trả kết quả) lặp tối đa max_rounds lần -> câu trả lời.
    Lượt cuối luôn tắt công cụ để model buộc phải trả lời bằng chữ.
    run_tool(name, args) là coroutine trả về dict; nó chịu trách nhiệm phân quyền và kiểm tra an toàn.
    Trả về (answer, input_tokens, output_tokens, model, số_lần_gọi_công_cụ).
    """
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("LLM_PROVIDER=gemini but GEMINI_API_KEY is missing.")

    selected = model or os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
    tool = types.Tool(function_declarations=[_declaration(spec) for spec in specs])

    contents = [types.Content(role="user", parts=[types.Part(text=prompt)])]
    input_tokens = output_tokens = calls_made = 0
    response = None

    client = genai.Client(api_key=api_key)
    try:
        for round_no in range(max_rounds + 1):
            allow_tools = round_no < max_rounds
            response = await client.aio.models.generate_content(
                model=selected,
                contents=contents,
                config=types.GenerateContentConfig(
                    temperature=float(os.getenv("GEMINI_TEMPERATURE", "0.2")),
                    max_output_tokens=int(os.getenv("GEMINI_MAX_OUTPUT_TOKENS", "2048")),
                    tools=[tool] if allow_tools else None,
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(
                        disable=True
                    ),
                ),
            )

            usage = response.usage_metadata
            input_tokens += getattr(usage, "prompt_token_count", 0) or 0
            output_tokens += getattr(usage, "candidates_token_count", 0) or 0

            calls = (response.function_calls or []) if allow_tools else []
            if not calls:
                break

            # Giữ nguyên lượt của model (kể cả thought signature) khi gửi lại.
            contents.append(response.candidates[0].content)

            parts = []
            for index, call in enumerate(calls):
                if index < max_calls_per_round:
                    calls_made += 1
                    result = await run_tool(call.name, dict(call.args or {}))
                else:
                    result = {"error": "Quá nhiều lời gọi công cụ trong một bước."}
                parts.append(
                    types.Part.from_function_response(name=call.name, response=result)
                )
            contents.append(types.Content(role="user", parts=parts))
    finally:
        await client.aio.aclose()

    answer = (response.text or "").strip() if response is not None else ""
    if not answer:
        raise RuntimeError(
            "Gemini returned an empty response after tool calls. "
            "Check the model response or safety feedback."
        )

    return answer, input_tokens, output_tokens, selected, calls_made