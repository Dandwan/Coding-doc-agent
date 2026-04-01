from __future__ import annotations

import json
import re
from typing import Any


def parse_tag_values(text: str, open_tag: str, close_tag: str) -> list[str]:
    if not open_tag or not close_tag:
        return []

    pattern = re.compile(re.escape(open_tag) + r"(.*?)" + re.escape(close_tag), re.DOTALL)
    values = [match.strip() for match in pattern.findall(text) if str(match).strip()]
    return values


def parse_questions_and_options(
    text: str,
    *,
    question_open: str,
    question_close: str,
    option_open: str,
    option_close: str,
) -> list[dict[str, Any]]:
    if not text.strip() or not question_open or not question_close:
        return []

    q_token = re.escape(question_open) + r".*?" + re.escape(question_close)
    o_token = re.escape(option_open) + r".*?" + re.escape(option_close)
    token_pattern = re.compile(f"({q_token}|{o_token})", re.DOTALL)

    parsed: list[dict[str, Any]] = []
    current_index = -1

    for token_match in token_pattern.finditer(text):
        token = token_match.group(0)
        if token.startswith(question_open):
            question_text = _strip_wrapped(token, question_open, question_close)
            if question_text:
                parsed.append({"question": question_text, "options": []})
                current_index = len(parsed) - 1
            continue

        if token.startswith(option_open) and current_index >= 0:
            option_text = _strip_wrapped(token, option_open, option_close)
            if option_text:
                parsed[current_index]["options"].append(option_text)

    return parsed


def parse_llm_json(raw_text: str) -> dict[str, Any]:
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = _strip_code_fence(cleaned)

    data = _try_load_json(cleaned)
    if data is None:
        data = _try_load_json(_extract_json_block(cleaned))

    if not isinstance(data, dict):
        raise ValueError("LLM 返回格式错误，无法解析为 JSON 对象")

    next_question = str(data.get("next_question", "请继续补充你的需求重点。")).strip()

    options = data.get("options")
    if not isinstance(options, list):
        options = []
    options = [str(item).strip() for item in options if str(item).strip()]
    if len(options) < 3:
        options.extend(["继续细化功能", "明确输入输出", "补充约束条件"])
    options = options[:5]

    unresolved = data.get("unresolved_points")
    if not isinstance(unresolved, list):
        unresolved = []
    unresolved = [str(item).strip() for item in unresolved if str(item).strip()]

    document_markdown = str(data.get("document_markdown", "")).strip()
    is_complete = bool(data.get("is_complete", False))

    return {
        "next_question": next_question,
        "options": options,
        "unresolved_points": unresolved,
        "document_markdown": document_markdown,
        "is_complete": is_complete,
    }


def _strip_code_fence(text: str) -> str:
    text = re.sub(r"^```[a-zA-Z0-9_-]*\n", "", text)
    text = re.sub(r"\n```$", "", text)
    return text.strip()


def _extract_json_block(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < 0 or end <= start:
        return ""
    return text[start : end + 1]


def _try_load_json(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    try:
        loaded = json.loads(text)
        return loaded if isinstance(loaded, dict) else None
    except json.JSONDecodeError:
        return None


def _strip_wrapped(token: str, open_tag: str, close_tag: str) -> str:
    value = token[len(open_tag) :]
    if value.endswith(close_tag):
        value = value[: -len(close_tag)]
    return value.strip()
