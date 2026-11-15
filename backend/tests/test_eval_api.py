"""The Evaluation screen's data: every kind of recorded result, summarised, without per-item rows."""

import json


async def test_recorded_results_of_each_kind_are_listed_in_summary(team, tmp_path, monkeypatch):
    from app.api import evaluation

    (tmp_path / "test-m.json").write_text(
        json.dumps(
            {
                "name": "test-m",
                "model": "m",
                "split": "test",
                "metrics": {"pass_rate": 0.9},
                "by_kind": {},
                "questions": [1],
            }
        )
    )
    (tmp_path / "retrieval.json").write_text(
        json.dumps({"name": "retrieval", "n": 36, "recall_at_3": 0.78, "questions": [1]})
    )
    (tmp_path / "wer-base.en-cpu.json").write_text(
        json.dumps(
            {
                "name": "wer-base.en-cpu",
                "model": "base.en",
                "device": "cpu",
                "by_condition": {"clean": {"wer": 0.08}},
                "rows": [1],
            }
        )
    )
    (tmp_path / "attacks-m.json").write_text(json.dumps({"model": "m", "cases": [{"id": "loop", "result": "held"}]}))
    monkeypatch.setattr(evaluation, "RESULTS", tmp_path)
    body = (await team.viewer.get("/api/eval/results")).json()
    assert body["results"][0]["metrics"]["pass_rate"] == 0.9 and "questions" not in body["results"][0]
    assert body["retrieval"][0]["recall_at_3"] == 0.78 and "questions" not in body["retrieval"][0]
    assert body["wer"][0]["by_condition"]["clean"]["wer"] == 0.08 and "rows" not in body["wer"][0]
    assert body["attacks"][0]["cases"][0]["result"] == "held"
