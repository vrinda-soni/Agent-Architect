"""
json_utils.py
-------------
Shared utility for robust JSON extraction from LLM outputs.
Handles truncated/malformed JSON without requiring external libraries.
"""

import json
import re


def _close_truncated_json(text: str) -> str:
    """
    Close an incomplete/truncated JSON string by tracking open
    strings, arrays, and objects, then appending the right closers.
    """
    stack = []        # pending closers: '}' or ']'
    in_string = False
    escape_next = False

    for ch in text:
        if escape_next:
            escape_next = False
            continue
        if ch == '\\' and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == '{':
            stack.append('}')
        elif ch == '[':
            stack.append(']')
        elif ch in ('}', ']'):
            if stack and stack[-1] == ch:
                stack.pop()

    tail = text
    # Close any open string
    if in_string:
        tail += '"'

    # Strip trailing comma / whitespace before adding closers
    tail = tail.rstrip()
    while tail.endswith(','):
        tail = tail[:-1].rstrip()

    # Close open structures in reverse order
    for closer in reversed(stack):
        tail += closer

    return tail


def _recover_complete_items(text: str) -> list:
    """
    Extract every fully-closed JSON object from an 'items' array
    in truncated LLM output. Stops at the first incomplete object.
    Returns whatever complete items were found (may be empty list).
    """
    items_pos = text.find('"items"')
    if items_pos == -1:
        return []
    arr_start = text.find('[', items_pos)
    if arr_start == -1:
        return []

    items = []
    pos = arr_start + 1
    while pos < len(text):
        # skip whitespace / commas
        while pos < len(text) and text[pos] in ' \t\n\r,':
            pos += 1
        if pos >= len(text) or text[pos] in (']', '}'):
            break
        if text[pos] != '{':
            break

        # find closing brace for this object
        depth, in_str, escape, obj_end = 0, False, False, None
        for i in range(pos, len(text)):
            ch = text[i]
            if escape:
                escape = False
                continue
            if ch == '\\' and in_str:
                escape = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    obj_end = i
                    break

        if obj_end is None:
            break  # incomplete object — stop here

        try:
            obj = json.loads(text[pos:obj_end + 1])
            items.append(obj)
        except json.JSONDecodeError:
            break  # malformed object — stop

        pos = obj_end + 1

    return items


def extract_json(text: str) -> dict:
    """
    Robustly extract and repair a JSON object from raw LLM output.

    Handles:
    - Markdown code blocks
    - Trailing commas, single quotes, Python literals
    - Truncated / incomplete JSON (no external library needed)
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
        end = None
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
        if end is not None:
            candidate = text[start:end + 1]
        else:
            # Truncated response — closing brace never found
            candidate = text[start:]
    else:
        candidate = text

    # 3. Try standard parse first (fastest path)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    # 4. Manual fixes: Python literals, trailing commas, then retry
    fixed = candidate
    fixed = re.sub(r'\bNone\b', 'null', fixed)
    fixed = re.sub(r'\bTrue\b', 'true', fixed)
    fixed = re.sub(r'\bFalse\b', 'false', fixed)
    fixed = re.sub(r',(\s*[}\]])', r'\1', fixed)
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    # 5. Close truncated JSON and retry
    try:
        closed = _close_truncated_json(fixed)
        # Apply trailing-comma fix again after closing
        closed = re.sub(r',(\s*[}\]])', r'\1', closed)
        return json.loads(closed)
    except (json.JSONDecodeError, Exception):
        pass

    # 6. Try json_repair if available (optional dependency)
    try:
        from json_repair import repair_json
        repaired = repair_json(candidate, return_objects=True)
        if isinstance(repaired, dict):
            return repaired
        if isinstance(repaired, str):
            return json.loads(repaired)
    except Exception:
        pass

    # 7. Last resort: close + repair full original text
    try:
        closed_full = _close_truncated_json(text[start:] if start != -1 else text)
        closed_full = re.sub(r',(\s*[}\]])', r'\1', closed_full)
        return json.loads(closed_full)
    except Exception:
        pass

    # 8. Nuclear fallback: extract only the complete items we can find
    recovered = _recover_complete_items(text)
    if recovered:
        print(f"[json_utils] Recovered {len(recovered)} complete items from truncated output")
        iface_types = list({i.get("interface_type", "") for i in recovered if i.get("interface_type")})
        eng_types   = list({i.get("engineer_type",  "") for i in recovered if i.get("engineer_type")})
        return {
            "items": recovered,
            "interface_types": iface_types,
            "engineer_types":  eng_types,
            "assumptions": [],
        }

    raise ValueError(
        f"Could not extract valid JSON from LLM output (first 500 chars):\n{text[:500]}"
    )
