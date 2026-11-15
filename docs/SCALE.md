# Scale and latency

How long a caller waits for an answer, and how that changes with calls at once. Measured on 2026-11-14 with
`backend/load/voice_load.py`, which streams recorded customer speech over the voice socket in real time, through
nginx, as a browser does. Results are appended to `backend/load/results/voice_latency.jsonl`.

```bash
cd backend && uv run python -m load.voice_load --calls 4 --turns 3 --tag "gpu small.en, demo model, 4 calls"
```

## What is measured

- **Perceived**: from the last sample of the customer's speech leaving the client to the first byte of the answer's
  audio arriving. This is the pause a caller hears. It includes the 600 ms of silence that ends a turn
  (`VAD_SILENCE_MS`).
- **Server**: from the server detecting the end of speech to its first audio byte, split into recognition (and time
  queued for the recogniser), the agent, and synthesis of the first sentence.

The agent here is the **demo model** (`LLM_PROVIDER=stub` with the scripted demo responder), so these runs measure
the speech path and the server, not a hosted model. A real model adds its own time to every turn: in the evaluation,
whole turns through Claude Sonnet 5.5 took 2.5 s at p50 (GPT-6 Sol 4.0 s), including tool calls (`EVALUATION.md`).
Expect a perceived pause of roughly the figures below plus that.

## Results

Speech recognition on the CPU (Whisper base.en, int8), the default compose:

| Calls at once | Perceived p50 / p95 | Server p50 / p95 | Recognition p50 | Waiting for the recogniser p50 |
|---|---|---|---|---|
| 1 | 2.8 s / 3.8 s | 2.1 s / 3.1 s | 1.5 s | 0 |
| 2 | 3.8 s / 4.4 s | 3.1 s / 3.7 s | 2.0 s | 0 |
| 4 | 5.9 s / 7.3 s | 5.2 s / 6.7 s | 1.9 s | 1.4 s |

Speech recognition on the GPU (Whisper small.en, float16, `docker-compose.gpu.yml`, an RTX-class card):

| Calls at once | Perceived p50 / p95 | Server p50 / p95 | Recognition p50 | Agent p50 | First sentence spoken p50 |
|---|---|---|---|---|---|
| 1 | 1.64 s / 4.73 s | 1.01 s / 4.07 s | 0.25 s | 0.11 s | 0.27 s |
| 2 | 1.34 s / 1.97 s | 0.70 s / 1.30 s | 0.15 s | 0.13 s | 0.23 s |
| 4 | 1.73 s / 2.78 s | 1.22 s / 2.13 s | 0.17 s | 0.14 s | 0.50 s |
| 8 | 2.52 s / 3.73 s | 1.92 s / 2.97 s | 0.20 s | 0.48 s | 0.43 s |

The one-call GPU p95 is the first turn after start, which loads the model onto the card; later turns were under
1.5 s.

## What the numbers say

- **On the CPU, recognition is the limit.** One process recognises one utterance at a time; at four calls, turns
  queue for it (1.4 s at p50) and the pause passes five seconds. The CPU build is for a demo or one or two callers.
- **On the GPU, recognition stops mattering**: a fifth of a second, even at eight calls. The pause is then the
  silence that ends a turn, the agent, and synthesis.
- **Synthesis (Piper on the CPU) becomes the next limit** as calls grow: the first sentence takes about 0.2 s alone and
  0.4 to 0.5 s at four to eight calls, because synthesis shares the API process's CPU.
- **With a hosted model, the model is the largest part of the pause.** Replies are spoken a sentence at a time as they
  are synthesised, but the model's reply is not streamed; streaming it into synthesis is the next latency
  improvement.

## Scaling out

- **API processes** are stateless between turns: the call's state is in PostgreSQL (the LangGraph checkpoint, turns,
  events), a Redis lock serialises turns of one call across processes, and live events go through Redis streams. A
  voice socket is held by the process that accepted it, so a load balancer needs nothing sticky beyond the socket
  itself. Add API containers to add calls.
- **Recognition and synthesis** run inside each API process. On a GPU host, one card serves several API processes;
  past that, `STT_PROVIDER=openai_compat` / `TTS_PROVIDER=openai_compat` move them to a separate service (a hosted API
  or a self-hosted Whisper / TTS server) without code changes.
- **Limits that protect the service**: 20 live calls per organisation, 10 new calls a minute per person, per-turn and
  per-call model budgets, and daily spend limits per organisation and across all organisations (`SECURITY.md`). A
  request that cannot get a database connection gets 503 with `Retry-After`.

## Caveats

- **A shared machine.** These runs shared a 16-core workstation with another project's container using 5 to 7 cores
  throughout; the CPU figures in particular would be better on a dedicated host.
- **Synthetic callers.** The customer's voice is Piper (en_US-ryan-medium), cleaner and steadier than a person on a
  phone, and the network is local: add the caller's round trip in production.
- **Short runs**: three measured turns per call, 3 to 24 turns per row. They show the shape, not a capacity
  guarantee.
- **The rate limit is per person**, and the load script places every call as one signed-in agent, so runs placing
  more than ten calls a minute meet it; the runs were spaced to stay under it.
