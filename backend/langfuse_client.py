"""
langfuse_client.py
------------------
Singleton Langfuse client for observability and debugging.
Provides trace/span helpers used across all agents and the LLM client.

Usage:
    from backend.langfuse_client import get_langfuse, create_trace, create_span, flush

Set in .env:
    LANGFUSE_PUBLIC_KEY=pk-lf-...
    LANGFUSE_SECRET_KEY=sk-lf-...
    LANGFUSE_HOST=https://cloud.langfuse.com   (or self-hosted URL)
"""

import os
from dotenv import load_dotenv

load_dotenv()

LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "").strip()
LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "").strip()
LANGFUSE_HOST = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com").strip()

_langfuse = None


def get_langfuse():
    """Return the singleton Langfuse client, or None if not configured."""
    global _langfuse
    if _langfuse is not None:
        return _langfuse

    if not LANGFUSE_PUBLIC_KEY or not LANGFUSE_SECRET_KEY:
        return None

    if LANGFUSE_PUBLIC_KEY.startswith("your_") or LANGFUSE_SECRET_KEY.startswith("your_"):
        return None

    try:
        from langfuse import Langfuse
        _langfuse = Langfuse(
            public_key=LANGFUSE_PUBLIC_KEY,
            secret_key=LANGFUSE_SECRET_KEY,
            host=LANGFUSE_HOST,
        )
        return _langfuse
    except Exception as e:
        print(f"[Langfuse] Failed to initialize: {e}")
        return None


def create_trace(name: str, metadata: dict = None, user_id: str = None, session_id: str = None):
    """
    Create a new Langfuse trace. Returns the trace object or a no-op stub if Langfuse is not configured.
    """
    lf = get_langfuse()
    if lf is None:
        return _NoOpTrace()
    kwargs = {"name": name}
    if metadata:
        kwargs["metadata"] = metadata
    if user_id:
        kwargs["user_id"] = user_id
    if session_id:
        kwargs["session_id"] = session_id
    try:
        return lf.trace(**kwargs)
    except Exception as e:
        print(f"[Langfuse] create_trace failed: {e}")
        return _NoOpTrace()


def create_span(parent, name: str, input=None, metadata: dict = None):
    """
    Create a child span under a trace (or another span). Returns the span object,
    or None when no parent is given — so callers can fall back to standalone tracing.
    """
    if parent is None:
        return None
    try:
        kwargs = {"name": name}
        if input is not None:
            kwargs["input"] = input
        if metadata:
            kwargs["metadata"] = metadata
        return parent.span(**kwargs)
    except Exception as e:
        print(f"[Langfuse] create_span failed: {e}")
        return _NoOpSpan()


def flush():
    """Flush pending Langfuse events (call at end of request/process)."""
    lf = get_langfuse()
    if lf:
        try:
            lf.flush()
        except Exception:
            pass


# -----------------------------------------------------------------
# No-Op stubs — used when Langfuse is not configured so agents work
# normally without any code changes.
# -----------------------------------------------------------------

class _NoOpGeneration:
    def end(self, **kwargs): pass
    def update(self, **kwargs): pass


class _NoOpSpan:
    def generation(self, **kwargs): return _NoOpGeneration()
    def span(self, **kwargs): return _NoOpSpan()
    def end(self, **kwargs): pass
    def update(self, **kwargs): pass


class _NoOpTrace:
    def generation(self, **kwargs): return _NoOpGeneration()
    def span(self, **kwargs): return _NoOpSpan()
    def end(self, **kwargs): pass
    def update(self, **kwargs): pass
