"""
llm_client.py
-------------
Unified LLM client with Gemini primary and OpenRouter fallback chain.
If Gemini API quota/rate-limit is exceeded, automatically falls back
through a per-agent chain of confirmed-working free models on OpenRouter.

All calls are traced via Langfuse when configured.
"""

import os
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()

_gemini_client = None
if GEMINI_API_KEY:
    _gemini_client = genai.Client(api_key=GEMINI_API_KEY)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MISTRAL_URL = "https://api.mistral.ai/v1/chat/completions"
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "").strip()
GEMINI_MODEL = "gemini-2.0-flash"

# Mistral model to use as the first fallback for specific agents
# Note: mistral-medium-2505 supports up to 8,191 output tokens
# planning_agent  ≈ 6,000–7,000 tokens  → safe
# estimation_agent ≈ 7,500 tokens         → borderline, falls back to OpenRouter if exceeded
_AGENT_MISTRAL_MODEL: dict[str, str] = {
    "estimation_agent": "mistral-medium-2505",
    "planning_agent":   "mistral-medium-2505",
}

# Per-agent fallback chains.
# Rules:
#   - estimation_agent: NEVER use llama-3.3 (2048 output cap truncates large JSON)
#   - planning_agent:   needs strong reasoning; deepseek-r1 is good here
#   - qa_agent:         short answers → cheap/free models are fine; llama-3.3 is acceptable
#   - default:          safe full chain used for any agent not listed below
_AGENT_FALLBACKS: dict[str, list[str]] = {
    "task_agent": [
        "nvidia/nemotron-3-super-120b-a12b:free",
        "openai/gpt-oss-120b:free",
        "nvidia/nemotron-3-ultra-550b-a55b:free",
        "qwen/qwen3-coder:free",
        "nousresearch/hermes-3-llama-3.1-405b:free",
        "google/gemma-4-31b-it:free",
        "qwen/qwen3-next-80b-a3b-instruct:free",
    ],
    "planning_agent": [
        "nvidia/nemotron-3-super-120b-a12b:free",
        "openai/gpt-oss-120b:free",
        "nvidia/nemotron-3-ultra-550b-a55b:free",
        "qwen/qwen3-coder:free",
        "nousresearch/hermes-3-llama-3.1-405b:free",
        "google/gemma-4-31b-it:free",
        "qwen/qwen3-next-80b-a3b-instruct:free",
    ],
    "feasibility_agent": [
        "nvidia/nemotron-3-super-120b-a12b:free",
        "openai/gpt-oss-120b:free",
        "nvidia/nemotron-3-ultra-550b-a55b:free",
        "qwen/qwen3-coder:free",
        "nousresearch/hermes-3-llama-3.1-405b:free",
        "google/gemma-4-31b-it:free",
        "qwen/qwen3-next-80b-a3b-instruct:free",
    ],
    "estimation_agent": [
        # All have large output caps (32k+) — safe for big JSON responses
        "nvidia/nemotron-3-super-120b-a12b:free",
        "openai/gpt-oss-120b:free",
        "nvidia/nemotron-3-ultra-550b-a55b:free",
        "qwen/qwen3-coder:free",
        "nousresearch/hermes-3-llama-3.1-405b:free",
        "google/gemma-4-31b-it:free",
        "qwen/qwen3-next-80b-a3b-instruct:free",
    ],
    "report_agent": [
        # All have large output caps — safe for long report generation
        "nvidia/nemotron-3-super-120b-a12b:free",
        "openai/gpt-oss-120b:free",
        "nvidia/nemotron-3-ultra-550b-a55b:free",
        "qwen/qwen3-coder:free",
        "nousresearch/hermes-3-llama-3.1-405b:free",
        "google/gemma-4-31b-it:free",
        "qwen/qwen3-next-80b-a3b-instruct:free",
    ],
    "qa_agent": [
        "nvidia/nemotron-3-super-120b-a12b:free",
        "openai/gpt-oss-120b:free",
        "nvidia/nemotron-3-ultra-550b-a55b:free",
        "qwen/qwen3-coder:free",
        "nousresearch/hermes-3-llama-3.1-405b:free",
        "google/gemma-4-31b-it:free",
        "meta-llama/llama-3.3-70b-instruct:free",
    ],
}

# Default fallback chain for any agent not listed above
FALLBACK_MODELS = [
    "nvidia/nemotron-3-super-120b-a12b:free",
    "openai/gpt-oss-120b:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "qwen/qwen3-coder:free",
    "nousresearch/hermes-3-llama-3.1-405b:free",
    "google/gemma-4-31b-it:free",
    "qwen/qwen3-next-80b-a3b-instruct:free",
]


# -----------------------------------------------------------------
# Helper to detect quota / rate-limit errors
# -----------------------------------------------------------------
def _is_quota_or_rate_limit_error(exc: Exception) -> bool:
    """Check if an exception is a quota, rate-limit, or exhaustion error."""
    error_str = str(exc).lower()
    keywords = [
        "quota", "rate limit", "exhausted", "limit exceeded",
        "429", "403", "resource exhausted", "billing",
        "insufficient quota", "too many requests",
    ]
    return any(kw in error_str for kw in keywords)


# -----------------------------------------------------------------
# OpenRouter call
# -----------------------------------------------------------------
def _call_openrouter(prompt: str, model: str, generation=None, max_tokens: int = None, timeout: int = 45) -> str:
    """Call OpenRouter with a specific model."""
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
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
    }
    if max_tokens:
        payload["max_tokens"] = max_tokens

    start = time.time()
    resp = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=timeout)
    if not resp.ok:
        try:
            body = resp.json()
        except Exception:
            body = resp.text
        print(f"[OpenRouter] HTTP {resp.status_code} for model '{model}': {body}")
    resp.raise_for_status()
    data = resp.json()
    elapsed = round(time.time() - start, 2)

    if "choices" not in data or not data["choices"]:
        raise ValueError(f"OpenRouter returned empty choices. Response: {data}")

    output = data["choices"][0]["message"]["content"]

    if generation:
        try:
            usage = data.get("usage", {})
            generation.end(
                output=output,
                model=model,
                usage={
                    "input": usage.get("prompt_tokens"),
                    "output": usage.get("completion_tokens"),
                    "total": usage.get("total_tokens"),
                },
                metadata={"provider": "openrouter", "latency_s": elapsed},
            )
        except Exception:
            pass

    return output


# -----------------------------------------------------------------
# Mistral call (direct API)
# -----------------------------------------------------------------
def _call_mistral(prompt: str, model: str, generation=None, max_tokens: int = None) -> str:
    """Call Mistral's own API directly."""
    if not MISTRAL_API_KEY:
        raise ValueError("MISTRAL_API_KEY is not set.")

    headers = {
        "Authorization": f"Bearer {MISTRAL_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
    }
    if max_tokens:
        payload["max_tokens"] = max_tokens

    start = time.time()
    resp = requests.post(MISTRAL_URL, headers=headers, json=payload, timeout=120)
    if not resp.ok:
        try:
            body = resp.json()
        except Exception:
            body = resp.text
        print(f"[Mistral] HTTP {resp.status_code} for model '{model}': {body}")
    resp.raise_for_status()
    data = resp.json()
    elapsed = round(time.time() - start, 2)

    if "choices" not in data or not data["choices"]:
        raise ValueError(f"Mistral returned empty choices. Response: {data}")

    output = data["choices"][0]["message"]["content"]

    if generation:
        try:
            usage = data.get("usage", {})
            generation.end(
                output=output,
                model=model,
                usage={
                    "input": usage.get("prompt_tokens"),
                    "output": usage.get("completion_tokens"),
                    "total": usage.get("total_tokens"),
                },
                metadata={"provider": "mistral", "latency_s": elapsed},
            )
        except Exception:
            pass

    return output


# -----------------------------------------------------------------
# Gemini call
# -----------------------------------------------------------------
def _call_gemini(prompt: str, use_search: bool = False, generation=None, max_tokens: int = None) -> str:
    """Call Gemini with optional Google Search grounding."""
    if not _gemini_client or not GEMINI_API_KEY:
        raise ValueError("Gemini API key is not set.")

    config = types.GenerateContentConfig()
    if use_search:
        config.tools = [{"google_search": {}}]
    if max_tokens:
        config.max_output_tokens = max_tokens

    start = time.time()
    response = _gemini_client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=config,
    )
    elapsed = round(time.time() - start, 2)
    output = response.text

    if generation:
        try:
            usage = getattr(response, "usage_metadata", None)
            generation.end(
                output=output,
                model=GEMINI_MODEL,
                usage={
                    "input": getattr(usage, "prompt_token_count", None),
                    "output": getattr(usage, "candidates_token_count", None),
                    "total": getattr(usage, "total_token_count", None),
                } if usage else None,
                metadata={"provider": "gemini", "latency_s": elapsed, "search": use_search},
            )
        except Exception:
            pass

    return output


# -----------------------------------------------------------------
# Per-agent OpenRouter timeout (seconds)
# Large-output agents need more time; others fail fast so next model can be tried
# -----------------------------------------------------------------
_AGENT_OPENROUTER_TIMEOUT: dict[str, int] = {
    "estimation_agent": 90,
    "report_agent":     90,
    "task_agent":       60,
    "planning_agent":   60,
    "feasibility_agent": 60,
}
_DEFAULT_OPENROUTER_TIMEOUT = 45


def _try_openrouter_parallel(
    prompt: str,
    models: list,
    token_limit: int | None,
    or_timeout: int,
    batch_size: int = 3,
    parent=None,
    agent_name: str = "llm_call",
) -> str:
    """
    Try OpenRouter models in parallel batches of `batch_size`.
    Returns the first successful response; raises if all fail.
    Each model attempt is recorded as a Langfuse generation under `parent`.
    """
    last_error: Exception | None = None
    batches = [models[i : i + batch_size] for i in range(0, len(models), batch_size)]

    for batch in batches:
        print(f"[LLM] Parallel batch: {[m.split('/')[0] for m in batch]}")
        winner = None
        gens: dict = {}
        with ThreadPoolExecutor(max_workers=len(batch)) as executor:
            future_to_model = {}
            for m in batch:
                gen = None
                if parent is not None:
                    try:
                        gen = parent.generation(
                            name=f"{agent_name}:openrouter:{m}",
                            model=m,
                            input=prompt,
                            metadata={"provider": "openrouter", "max_tokens": token_limit},
                        )
                    except Exception:
                        gen = None
                gens[m] = gen
                future_to_model[
                    executor.submit(_call_openrouter, prompt, m, gen, token_limit, or_timeout)
                ] = m
            # Let every future finish (the executor waits at block exit anyway) so we
            # can close each generation, while keeping the FIRST success as the winner.
            for future in as_completed(future_to_model):
                model = future_to_model[future]
                try:
                    result = future.result()
                    if winner is None:
                        winner = result
                        print(f"[LLM] OK  {model} succeeded (parallel)")
                except Exception as e:
                    last_error = e
                    if gens.get(model):
                        try:
                            gens[model].end(level="ERROR", status_message=str(e))
                        except Exception:
                            pass
                    print(f"[LLM] FAIL {model} failed: {e}")
        if winner is not None:
            return winner

    raise ValueError(f"All parallel OpenRouter fallbacks failed. Last: {last_error}") from last_error


# -----------------------------------------------------------------
# Public API: generate with fallback + Langfuse tracing
# -----------------------------------------------------------------
# Per-agent output token limits — balances quality vs cost
_AGENT_MAX_TOKENS = {}  # no output token caps — let the model respond fully


def generate_with_fallback(
    prompt: str,
    use_search: bool = False,
    trace=None,
    agent_name: str = "llm_call",
    max_tokens: int = None,
) -> str:
    """
    Generate text using Gemini first. If quota/rate-limit is hit,
    automatically fall back through the OpenRouter model chain.
    All calls are traced via Langfuse when a trace object is provided.

    Args:
        prompt:      The full prompt text.
        use_search:  Enable Google Search grounding on Gemini.
        trace:       Optional Langfuse trace object (from create_trace()).
        agent_name:  Label for this generation in Langfuse.

    Returns:
        Raw text response from the model.
    """
    from backend.langfuse_client import create_trace, flush

    # Resolve token limit: explicit arg > per-agent default > None (no cap)
    token_limit = max_tokens or _AGENT_MAX_TOKENS.get(agent_name)

    # Use provided trace or create a standalone one
    active_trace = trace or create_trace(name=agent_name, metadata={"prompt_len": len(prompt)})

    # Agents that we want to explicitly skip Gemini for (to avoid the 60s quota failure penalty)
    _BYPASS_GEMINI_AGENTS = {"estimation_agent", "planning_agent"}

    # Try Gemini first
    if _gemini_client and GEMINI_API_KEY and agent_name not in _BYPASS_GEMINI_AGENTS:
        gen = None
        try:
            gen = active_trace.generation(
                name=f"{agent_name}:gemini",
                model=GEMINI_MODEL,
                input=prompt,
                metadata={"provider": "gemini", "max_tokens": token_limit},
            )
            result = _call_gemini(prompt, use_search=use_search, generation=gen, max_tokens=token_limit)
            if trace is None:
                flush()
            return result
        except Exception as e:
            if gen:
                try:
                    gen.end(level="ERROR", status_message=str(e))
                except Exception:
                    pass
            if _is_quota_or_rate_limit_error(e):
                pass  # fall through to OpenRouter
            else:
                if trace is None:
                    flush()
                raise

    # Try Mistral directly if configured for this agent
    mistral_model = _AGENT_MISTRAL_MODEL.get(agent_name)
    if mistral_model and MISTRAL_API_KEY:
        gen = None
        try:
            print(f"[LLM] Trying Mistral ({mistral_model}) for '{agent_name}'...")
            gen = active_trace.generation(
                name=f"{agent_name}:mistral",
                model=mistral_model,
                input=prompt,
                metadata={"provider": "mistral", "max_tokens": token_limit},
            )
            result = _call_mistral(prompt, model=mistral_model, generation=gen, max_tokens=token_limit)
            print(f"[LLM] OK  Mistral ({mistral_model}) succeeded for '{agent_name}'")
            if trace is None:
                flush()
            return result
        except Exception as e:
            print(f"[LLM] FAIL Mistral ({mistral_model}) failed: {e}")
            if gen:
                try:
                    gen.end(level="ERROR", status_message=str(e))
                except Exception:
                    pass

    # Fallback chain through OpenRouter models (agent-specific or default)
    fallback_list = _AGENT_FALLBACKS.get(agent_name, FALLBACK_MODELS)
    or_timeout = _AGENT_OPENROUTER_TIMEOUT.get(agent_name, _DEFAULT_OPENROUTER_TIMEOUT)
    print(f"[LLM] Gemini quota hit for '{agent_name}'. Trying {len(fallback_list)} OpenRouter fallbacks in parallel batches (timeout={or_timeout}s each)...")

    try:
        result = _try_openrouter_parallel(
            prompt, fallback_list, token_limit, or_timeout,
            parent=active_trace, agent_name=agent_name,
        )
        if trace is None:
            flush()
        return result
    except Exception as last_error:
        if trace is None:
            flush()
        raise ValueError(
            f"All models failed (Gemini + {len(fallback_list)} OpenRouter fallbacks for '{agent_name}'). "
            f"Last error: {last_error}"
        ) from last_error
