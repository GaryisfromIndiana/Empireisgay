"""Deterministic tests for LLM schema parsing helpers."""

from __future__ import annotations

from llm.schemas import AnalysisOutput, _extract_json_block, _find_json_object, parse_llm_output


def test_extract_json_from_markdown_block() -> None:
    payload = '```json\n{"summary": "from_md", "findings": []}\n```'
    extracted = _extract_json_block(payload)
    assert extracted == '{"summary": "from_md", "findings": []}'


def test_find_json_from_mixed_text() -> None:
    text = 'Plan:\n\n{"summary":"mixed","findings":[]}\nThanks.'
    extracted = _find_json_object(text)
    assert extracted == '{"summary":"mixed","findings":[]}'


def test_parse_llm_output_supports_mixed_content() -> None:
    output = "Model answer:\n\n```json\n{\"summary\":\"ok\",\"findings\":[]}\n```"
    parsed = parse_llm_output(output, AnalysisOutput)
    assert parsed is not None
    assert parsed.summary == "ok"
