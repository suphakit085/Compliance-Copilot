import re

import pytest
from sqlalchemy import text

from compliance_copilot import llm
from compliance_copilot.generation import prompts


@pytest.fixture(scope="session")
def corpus():
    """Integration tests need Postgres up and the corpus ingested (`copilot setup`)."""
    from compliance_copilot.db import engine

    try:
        with engine().connect() as c:
            n = c.execute(text("SELECT count(*) FROM chunks")).scalar_one()
    except Exception as e:  # pragma: no cover - environment dependent
        pytest.skip(f"database unavailable: {e}")
    if not n:
        pytest.skip("corpus not ingested")
    return n


class FakeLLM:
    """Deterministic stand-in: answers by quoting the first source verbatim."""

    name, model = "fake", "fake-llm"

    def __init__(self):
        self.calls = 0

    def generate_json(self, system, prompt, schema, images=None, effort=None):
        self.calls += 1
        if schema is prompts.GroundedAnswer:
            m = re.search(r'<source id="(S\d+)">.*?---\n(.*?)\n</source>', prompt, re.S)
            sid, body = m.group(1), m.group(2)
            quote = body[:60]
            out = prompts.GroundedAnswer(
                status="answered", answer=f"คำตอบทดสอบ [{sid}]",
                citations=[prompts.CitedQuote(source_id=sid, quote=quote)], follow_up_questions=[],
            )
            return out, llm.Usage(self.model, 100, 20)
        if schema is prompts.Standalone:
            return prompts.Standalone(question=prompt.rsplit("Latest message:", 1)[-1].strip()), llm.Usage(self.model)
        raise AssertionError(f"unexpected schema {schema}")

    def generate_text(self, system, prompt, images=None, effort=None):
        return "", llm.Usage(self.model)


@pytest.fixture
def fake_llm(monkeypatch):
    fake = FakeLLM()
    llm.set_provider(fake)
    monkeypatch.setattr(llm, "available", lambda: True)
    yield fake
    llm.set_provider(None)


@pytest.fixture(autouse=True)
def _fresh_rate_limits():
    """Rate-limit windows are process-wide; keep tests independent of each other."""
    from compliance_copilot.ratelimit import limiter

    limiter.reset()
    yield
    limiter.reset()
