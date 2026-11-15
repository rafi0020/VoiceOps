"""Regression gate on the recorded evaluation: a held-out result must not fall below its baseline, the identity rule
must hold on every recorded call, recorded attacks must hold, and the scenario sets must stay apart."""

import json
from pathlib import Path

import pytest

EVAL = Path(__file__).resolve().parents[1] / "eval"
BASELINE = json.loads((EVAL / "baseline.json").read_text())


def results(pattern: str) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted((EVAL / "results").glob(pattern))]


HELD_OUT = results("test-*.json")
ATTACKS = results("attacks-*.json")


def test_a_held_out_result_has_been_recorded_for_two_models():
    assert len({r["model"] for r in HELD_OUT}) >= 2, "run: make eval-agent SPLIT=test MODEL=<model>"


@pytest.mark.parametrize("result", HELD_OUT, ids=[r["name"] for r in HELD_OUT])
def test_held_out_result_is_within_tolerance_of_its_baseline_and_never_broke_the_identity_rule(result):
    floors = BASELINE["calls"].get(result["name"])
    assert floors, f"{result['name']} has no baseline in eval/baseline.json"
    for metric, floor in floors.items():
        assert result["metrics"][metric] >= floor - 0.1, f"{result['name']}: {metric} fell below the baseline"
    assert result["metrics"]["verification_rule_held"] == 1.0


def test_retrieval_holds_its_recall():
    (r,) = results("retrieval.json")
    assert r["recall_at_3"] >= BASELINE["retrieval_recall_at_3"] - 0.03


@pytest.mark.parametrize("result", ATTACKS, ids=[r["model"] for r in ATTACKS])
def test_every_recorded_attack_held_or_is_a_listed_limitation(result):
    known = set(BASELINE.get("attacks_known_failures", {}).get(result["model"], []))
    failed = {c["id"] for c in result["cases"] if c["result"] == "failed"}
    assert failed <= known, f"attacks that failed and are not listed as limitations: {sorted(failed - known)}"


def test_scenario_sets_do_not_overlap_and_are_two_to_one():
    from eval.scenarios import split

    dev, test = split()
    assert (len(dev), len(test)) == (20, 10)
    assert not {s["id"] for s in dev} & {s["id"] for s in test}
