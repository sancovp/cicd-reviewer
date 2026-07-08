#!/usr/bin/env python3
"""Unit tests for ci_agent.extract_text — the pure result-parsing logic.

build_agent()/main() need heaven-framework + a live MiniMax model, so they are covered
by the container E2E run (automation/cicd-reviewer task 5), not here.

Run: python3 tests/test_ci_agent.py
"""
import importlib.util
import os
import sys

# Load ci_agent by path (it's a CLI script, not an installed package). extract_text needs
# no heaven-framework, and ci_agent imports heaven lazily inside build_agent(), so this is cheap.
_CI_AGENT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ci_agent.py")
_spec = importlib.util.spec_from_file_location("ci_agent", _CI_AGENT)
ci_agent = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ci_agent)
extract_text = ci_agent.extract_text


# Class name must be exactly "AIMessage" — extract_text keys on __class__.__name__,
# mirroring langchain's real AIMessage (same check as grug_agent.py).
class AIMessage:
    def __init__(self, content):
        self.content = content


class _Human:  # non-AIMessage class name on purpose
    def __init__(self, content):
        self.content = content


class _History:
    def __init__(self, messages):
        self.messages = messages


def t_non_dict_stringified():
    assert extract_text("plain string") == "plain string"
    assert extract_text(None) == "None"


def t_prepared_message_wins():
    hist = _History([AIMessage("from history")])
    assert extract_text({"prepared_message": "prep", "history": hist}) == "prep"


def t_last_aimessage_from_history():
    hist = _History([AIMessage("first"), _Human("noise"), AIMessage("last review DONE")])
    assert extract_text({"history": hist}) == "last review DONE"


def t_empty_dict_returns_empty():
    assert extract_text({}) == ""
    assert extract_text({"history": _History([])}) == ""


def t_non_string_aimessage_content_coerced():
    hist = _History([AIMessage(["a", "b"])])
    assert extract_text({"history": hist}) == "['a', 'b']"


def run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("t_")]
    passed = 0
    for t in tests:
        try:
            t()
            passed += 1
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            print(f"FAIL {t.__name__}: {e}")
    print(f"\n{passed}/{len(tests)} passed")
    return passed == len(tests)


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
