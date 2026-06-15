"""
json_utils.py
-------------
Shared utility for robust JSON extraction from LLM outputs.
Uses json_repair for handling truncated/malformed JSON, with a manual fallback.
"""

import json
import re


def extract_json(text: str) -> dict:
    """
    Robustly extract and repair a JSON object from raw LLM output.

    Handles:
    - Markdown code blocks
    - Trailing commas, single quotes, Python literals
    - Truncated / incomplete JSON
    - Extra text before/after the JSON object
    """
    text = text.strip()

    # 1. Strip markdown code fences
    if "```" in text:
        text = re.sub(r'^```(?:json)?\s*\n?', '', text, flags=re.MULTILINE)
        text = re.sub(r'\n?```\s*$', '', text, flags=re.MULTILINE)
        text = text.strip()

    # 2. Find the outermost JSON object using brace counting
    start = text.find('{')
    if start != -1:
        depth = 0
        end = start
        in_string = False
        escape = False
        for i, ch in enumerate(text[start:], start):
            if escape:
                escape = False
                continue
            if ch == '\\' and in_string:
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
            if not in_string:
                if ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        end = i
                        break
        candidate = text[start:end + 1]
    else:
        candidate = text

    # 3. Try standard parse first (fastest path)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    # 4. Use json_repair to fix truncated/malformed JSON
    try:
        from json_repair import repair_json
        repaired = repair_json(candidate, return_objects=True)
        if isinstance(repaired, dict):
            return repaired
        # repair_json returned a string — parse it
        if isinstance(repaired, str):
            return json.loads(repaired)
    except Exception:
        pass

    # 5. Manual fixes: Python literals, trailing commas, then retry
    fixed = candidate
    fixed = re.sub(r'\bNone\b', 'null', fixed)
    fixed = re.sub(r'\bTrue\b', 'true', fixed)
    fixed = re.sub(r'\bFalse\b', 'false', fixed)
    fixed = re.sub(r',(\s*[}\]])', r'\1', fixed)
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    # 6. Last resort: repair the full original text
    try:
        from json_repair import repair_json
        repaired = repair_json(text, return_objects=True)
        if isinstance(repaired, dict):
            return repaired
    except Exception:
        pass

    raise ValueError(
        f"Could not extract valid JSON from LLM output (first 500 chars):\n{text[:500]}"
    )
