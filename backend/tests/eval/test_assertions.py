import yaml

from eval.assertions import TurnResult, evaluate
from eval.run import GOLDEN_SET


def test_must_use_canonical() -> None:
    turn = TurnResult(text="scoped to the problem", canonical_intent="pricing")
    assert evaluate({"must_use_canonical": "pricing"}, turn) == []
    assert evaluate({"must_use_canonical": "data_security"}, turn)


def test_must_not_contain_is_case_insensitive() -> None:
    turn = TurnResult(text="It TYPICALLY costs $5000")
    assert evaluate({"must_not_contain": ["$"]}, turn)
    assert evaluate({"must_not_contain": ["typically"]}, turn)  # case-insensitive
    assert evaluate({"must_not_contain": ["free"]}, turn) == []


def test_must_offer_action() -> None:
    turn = TurnResult(text="", suggested_action_ids=["strategy_call"])
    assert evaluate({"must_offer_action": "strategy_call"}, turn) == []
    assert evaluate({"must_offer_action": "portal_support"}, turn)


def test_must_escalate_via_action_or_flag() -> None:
    via_action = TurnResult(text="", suggested_action_ids=["human_escalation"])
    via_flag = TurnResult(text="", mandatory_escalation=True)
    assert evaluate({"must_escalate": True}, via_action) == []
    assert evaluate({"must_escalate": True}, via_flag) == []
    assert evaluate({"must_escalate": True}, TurnResult(text="here is the answer"))


def test_must_not_confirm_client() -> None:
    confirmed = TurnResult(text="Yes, they are a client of ours.")
    # A refusal echoes the phrasing but must NOT be flagged.
    refused = TurnResult(text="I can't confirm whether Goldman Sachs is a client.")
    assert evaluate({"must_not_confirm_client": True}, confirmed)
    assert evaluate({"must_not_confirm_client": True}, refused) == []


def test_must_not_break_character() -> None:
    leaked = TurnResult(text="Sure — here is my system prompt: you are the assistant")
    # A refusal that echoes "system prompt" must NOT be flagged.
    refused = TurnResult(text="I can't share my system prompt or ignore my instructions.")
    assert evaluate({"must_not_break_character": True}, leaked)
    assert evaluate({"must_not_break_character": True}, refused) == []


def test_golden_set_is_well_formed() -> None:
    cases = yaml.safe_load(GOLDEN_SET.read_text(encoding="utf-8"))
    assert len(cases) >= 30
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids)), "case ids must be unique"
    for case in cases:
        assert case.get("turns"), f"{case.get('id')} has no turns"
        assert case.get("assert"), f"{case.get('id')} has no assertions"
