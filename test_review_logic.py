"""
Offline tests for the pure logic in social_proof_oracle.py.

Plain Python, no GenLayer runtime needed: the helper functions
(_validate_review, _parse_llm_json, _reviews_agree, _passes, _dedupe_key) are
loaded straight from the contract source, so these tests always exercise the
exact code that gets deployed.

    python3 tests/test_review_logic.py
"""
import json
import pathlib
import typing

SRC = (pathlib.Path(__file__).parent.parent / "social_proof_oracle.py").read_text()
start = SRC.index('ERROR_EXPECTED = "[EXPECTED]"')
end = SRC.index("@allow_storage")
ns = {"json": json, "typing": typing}
exec(SRC[start:end], ns)
validate = ns["_validate_review"]
parse = ns["_parse_llm_json"]
agree = ns["_reviews_agree"]
passes = ns["_passes"]
dedupe_key = ns["_dedupe_key"]


def review(organic=True, meets=True, score=80, reasoning="ok"):
    return {"organic": organic, "meets_criteria": meets, "score": score, "reasoning": reasoning}


def rejects(case):
    try:
        validate(case)
    except ValueError:
        return True
    return False


# --- strict validation of the AI review -------------------------------------

def test_accepts_well_formed():
    assert validate(review()) == review()


def test_booleans_must_be_real_booleans():
    for bad in ("true", "false", "False", 0, 1, None):
        assert rejects(review(organic=bad)), bad
        assert rejects(review(meets=bad)), bad


def test_score_must_be_int_in_range():
    for bad in (True, False, 80.5, "80", None, -1, 101):
        assert rejects(review(score=bad)), bad
    assert validate(review(score=0))["score"] == 0
    assert validate(review(score=100))["score"] == 100


def test_reasoning_must_be_string_and_is_truncated():
    for bad in (5, None, ["a"], {"a": 1}):
        assert rejects(review(reasoning=bad)), bad
    assert len(validate(review(reasoning="x" * 900))["reasoning"]) == 500


def test_missing_fields_and_wrong_container():
    for field in ("organic", "meets_criteria", "score", "reasoning"):
        case = review()
        del case[field]
        assert rejects(case), field
    assert rejects([True, True, 80, "x"])
    assert rejects("not a dict")


# --- parsing of the raw model output ----------------------------------------

def test_parse_accepts_text_fenced_text_and_objects():
    assert parse('{"a": 1}') == {"a": 1}
    assert parse('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse({"a": 1}) == {"a": 1}


def test_parse_rejects_garbage():
    for bad in (None, 5, 1.5, True):
        try:
            parse(bad)
        except ValueError:
            continue
        raise AssertionError(f"accepted {bad!r}")
    try:
        parse("not json at all")
    except ValueError:
        return
    raise AssertionError("accepted invalid JSON")


# --- the equivalence check between two validators' reviews ------------------

def test_agree_when_decisions_match_and_scores_are_close():
    assert agree(review(score=80), review(score=95))
    assert agree(review(score=80), review(score=60))   # exactly at tolerance
    assert agree(review(score=80, reasoning="a"), review(score=80, reasoning="totally different"))


def test_disagree_when_scores_drift_too_far():
    assert not agree(review(score=80), review(score=59))


def test_disagree_when_any_decision_field_differs():
    assert not agree(review(organic=True), review(organic=False))
    assert not agree(review(meets=True), review(meets=False))


# --- pass/fail is computed by the contract, not by the model ----------------

def test_pass_requires_all_three_conditions():
    assert passes(review(organic=True, meets=True, score=60), 60)
    assert not passes(review(organic=False, meets=True, score=99), 60)
    assert not passes(review(organic=True, meets=False, score=99), 60)
    assert not passes(review(organic=True, meets=True, score=59), 60)


# --- deduplication ----------------------------------------------------------

def test_dedupe_key_ignores_whitespace_and_trailing_slash_only():
    assert dedupe_key(1, " https://x.test/a ") == dedupe_key(1, "https://x.test/a/")
    assert dedupe_key(1, "https://x.test/a") != dedupe_key(2, "https://x.test/a")
    assert dedupe_key(1, "https://x.test/a") != dedupe_key(1, "https://x.test/b")


# --- regressions from earlier GenLayer contracts ----------------------------

def test_no_response_format_argument():
    # response_format="json" returns an object, not text; this contract
    # parses defensively instead of relying on it.
    code = "\n".join(l for l in SRC.splitlines() if not l.strip().startswith("#"))
    assert "response_format=" not in code


def test_no_value_transfer_in_this_contract():
    # This primitive moves no funds, so it must contain no transfer calls.
    assert "emit_transfer" not in SRC
    assert "get_contract_at(" not in SRC


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("ok", t.__name__)
    print(f"{len(tests)} tests passed")
