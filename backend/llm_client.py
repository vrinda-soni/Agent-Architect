"""
llm_client.py
-------------
Unified LLM client with Gemini primary and OpenRouter fallback.
If Gemini API quota/rate-limit is exceeded, automatically falls back
to OpenRouter using moonshotai/kimi-k2.6:free.
"""

import os
import requests
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()

_gemini_client = None
if GEMINI_API_KEY:
    _gemini_client = genai.Client(api_key=GEMINI_API_KEY)

OPENROUTER_MODEL = "moonshotai/kimi-k2.6:free"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


# -----------------------------------------------------------------
# Helper to detect quota / rate-limit errors
# -----------------------------------------------------------------
def _is_quota_or_rate_limit_error(exc: Exception) -> bool:
    """Check if an exception is a quota, rate-limit, or exhaustion error."""
    error_str = str(exc).lower()
    keywords = [
        "quota",
        "rate limit",
        "exhausted",
        "limit exceeded",
        "429",
        "403",
        "resource exhausted",
        "billing",
        "insufficient quota",
        "too many requests",
    ]
    return any(kw in error_str for kw in keywords)


# -----------------------------------------------------------------
# OpenRouter call
# -----------------------------------------------------------------
def _call_openrouter(prompt: str) -> str:
    """Call OpenRouter with the fallback model."""
    if not OPENROUTER_API_KEY:
        raise ValueError(
            "OpenRouter API key is not set. Please add OPENROUTER_API_KEY to your .env file."
        )

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:8503",
        "X-Title": "AI-Powered POC Generator",
    }
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [{"role": "user", "content": prompt}],
    }

    resp = requests.post(
        OPENROUTER_URL,
        headers=headers,
        json=payload,
        timeout=180,
    )
    resp.raise_for_status()
    data = resp.json()

    if "choices" not in data or not data["choices"]:
        raise ValueError(f"OpenRouter returned empty choices. Response: {data}")

    return data["choices"][0]["message"]["content"]


# -----------------------------------------------------------------
# Gemini call
# -----------------------------------------------------------------
def _call_gemini(prompt: str, use_search: bool = False) -> str:
    """Call Gemini with optional Google Search grounding."""
    if not _gemini_client or not GEMINI_API_KEY:
        raise ValueError("Gemini API key is not set.")

    config = types.GenerateContentConfig()
    if use_search:
        config.tools = [{"google_search": {}}]

    response = _gemini_client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=config,
    )
    return response.text


# -----------------------------------------------------------------
# Public API: generate with fallback
# -----------------------------------------------------------------
def generate_with_fallback(prompt: str, use_search: bool = False) -> str:
    """
    Generate text using Gemini first. If quota/rate-limit is hit,
    automatically fall back to OpenRouter (moonshotai/kimi-k2.6:free).

    Args:
        prompt: The full prompt text.
        use_search: Whether to enable Google Search grounding on Gemini.
                    Ignored for OpenRouter fallback.

    Returns:
        Raw text response from the model.

    Raises:
        ValueError: If both Gemini and OpenRouter fail or keys are missing.
    """
    # Try Gemini first
    if _gemini_client and GEMINI_API_KEY:
        try:
            return _call_gemini(prompt, use_search=use_search)
        except Exception as e:
            if _is_quota_or_rate_limit_error(e):
                # Fall through to OpenRouter
                pass
            else:
                # Non-quota error — re-raise so caller knows something else broke
                raise

    # Fallback to OpenRouter
    try:
        return _call_openrouter(prompt)
    except Exception as e:
        raise ValueError(
            f"Both Gemini and OpenRouter failed. Last error: {e}"
        ) from e
