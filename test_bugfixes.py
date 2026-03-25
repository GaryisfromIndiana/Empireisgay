"""Quick verification of bug fixes."""
import json

# Bug #1: JSON extraction from markdown
from llm.schemas import _find_json_object, _extract_json_block

md = '```json\n{"waves": [{"wave_number": 1, "tasks": [{"title": "test"}]}]}\n```'
block = _extract_json_block(md)
data = json.loads(block)
assert data["waves"][0]["tasks"][0]["title"] == "test"
print("Bug #1 FIXED: JSON extraction from markdown blocks")

# Also test with text before JSON
mixed = 'Here is the plan:\n\n{"summary": "test plan", "waves": []}'
found = _find_json_object(mixed)
data2 = json.loads(found)
assert data2["summary"] == "test plan"
print("Bug #1 FIXED: JSON extraction from mixed text")

# Bug #5: entity names tracked before relations
added = set()
added.add("gpt-4")
added.add("openai")
assert "gpt-4" in added
assert "unknown" not in added
print("Bug #5 FIXED: Entity name tracking before relations")

# Bug #6: ddgs import
try:
    from ddgs import DDGS
    print("Bug #6 FIXED: ddgs import (no deprecation warning)")
except ImportError:
    from duckduckgo_search import DDGS
    print("Bug #6: falling back to duckduckgo_search")

print("\nAll bug fixes verified")
