"""
json_utils.py
-------------
Shared utility for robust JSON extraction from LLM outputs.
Handles markdown code blocks, trailing commas, extra text, and other common LLM quirks.
"""

import json
import re


def extract_json(text: str) -> dict:
    """
    Robustly extract a JSON object from raw LLM output.

    Handles:
    - Markdown code blocks (```json ... ```)
    - Extra text before/after the JSON
    - Trailing commas before } or ]
    - Escaped newlines in strings
    - Mixed newline formats

    Args:
        text: Raw text from LLM that should contain a JSON object.

    Returns:
        Parsed JSON as a dict.

    Raises:
        ValueError: If no valid JSON can be extracted.
    """
    text = text.strip()

    # 1. Remove markdown code blocks
    if "```" in text:
        text = re.sub(r'^```(?:json)?\s*\n?', '', text)
        text = re.sub(r'\n?```\s*$', '', text)
        text = text.strip()

    # 2. Extract JSON object boundaries (find outermost { ... })
    match = re.search(r'\{[\s\S]*\}', text)
    if match:
        text = match.group(0)

    # 3. Remove trailing commas before } or ]
    text = re.sub(r',(\s*[}\]])', r'\1', text)

    # 4. Try parsing
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 5. Last resort: flatten newlines and retry
    flattened = text.replace('\\n', ' ').replace('\n', ' ')
    match = re.search(r'\{[\s\S]*\}', flattened)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    raise ValueError(
        f"Could not extract valid JSON from LLM output (first 500 chars):\n{text[:500]}"
    )
