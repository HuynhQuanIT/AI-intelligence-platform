
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
