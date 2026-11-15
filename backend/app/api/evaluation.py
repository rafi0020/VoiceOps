"""Recorded evaluation results, for the Evaluation screen. The files are produced by the scripts in eval/ (scripted
calls, retrieval, word error rate, attacks) and shipped with the application; nothing here runs a model.

A run in which the provider never answered is listed apart, under `unavailable`, so an outage is not shown as the
model's score."""

import json
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends

from app.api.deps import current_user
from app.security.sessions import Principal

router = APIRouter(prefix="/api/eval", tags=["evaluation"])
RESULTS = Path(__file__).resolve().parents[2] / "eval" / "results"
SHOWN = ("name", "model", "split", "at", "n", "metrics", "by_kind", "note")
RETRIEVAL = ("name", "at", "n", "recall_at_3")
WER = ("name", "model", "device", "compute_type", "at", "n", "by_condition")


@lru_cache(maxsize=4)
def _load(signature: tuple) -> dict:
    out: dict[str, list] = {"results": [], "attacks": [], "unavailable": [], "retrieval": [], "wer": []}
    for path in sorted(RESULTS.glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if path.name.startswith("retrieval"):
            out["retrieval"].append({k: data[k] for k in RETRIEVAL if k in data})
        elif path.name.startswith("wer-"):
            out["wer"].append({k: data[k] for k in WER if k in data})
        elif "cases" in data:
            out["attacks"].append({k: data[k] for k in ("model", "at", "cases", "note") if k in data})
        elif data.get("provider_unavailable"):
            out["unavailable"].append({k: data.get(k) for k in ("name", "model", "split", "at", "n", "note")})
        elif "metrics" in data:
            out["results"].append({k: data[k] for k in SHOWN if k in data})
    return out


@router.get("/results")
async def results(_: Principal = Depends(current_user)) -> dict:
    signature = (
        tuple((p.name, p.stat().st_mtime_ns) for p in sorted(RESULTS.glob("*.json"))) if RESULTS.exists() else ()
    )
    return _load((str(RESULTS), signature))
