# Model providers and speech

This document covers the language model that the agent calls and the speech models (recognition and synthesis).
Every value below can be set in `.env` (copy `.env.example`) or in the environment. Keys shown here are placeholders:
never put a real key in a file that is committed, and set provider keys in `.env` or through the administration
screen, which stores them encrypted.

## How the model is chosen

1. **Environment.** `backend/app/config.py` reads `LLM_*` variables. `backend/app/llm/factory.py::environment_config`
   turns them into an `LLMConfig`. An unknown `LLM_PROVIDER` is a start-up error (it used to be replaced silently by `stub`) (check the value
   carefully: a typo gives a model that answers with rules).
2. **Organisation.** An administrator can save settings for an organisation on the administration screen, or with
   `PUT /api/settings/llm` (see `docs/API.md`). A saved row (`llm_settings`) replaces the environment's settings for
   that organisation entirely, including its fallback model and prices. `factory.load_config` decides which applies.
3. **Client.** `factory.get_client(org_id)` builds the provider for the chosen configuration. One provider instance, with
   its own HTTP connection pool, exists per distinct provider, base URL and key.

The agent (`app/agent/graph.py`) and the call summary (`app/calls/summary.py`) both use `get_client`. Speech does not.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `LLM_PROVIDER` | `stub` | `openai_compat`, `anthropic`, `ollama` or `stub` |
| `LLM_MODEL` | empty (reported as `stub`) | Model name the provider expects |
| `LLM_API_KEY` | empty | Key for the provider. Not needed for `ollama`, or for a gateway that does not check keys |
| `LLM_BASE_URL` | empty | Required for `openai_compat`; for `ollama` defaults to `http://localhost:11434/v1`; for `anthropic` defaults to `https://api.anthropic.com` |
| `LLM_FALLBACK_MODEL` | empty | Tried once, on the same provider, when the primary model has failed with a retryable error (see below) |
| `LLM_PRICE_INPUT_PER_MTOK` | `3.0` | USD per million input tokens, for cost estimates and the per-call cost cap. Set this to your provider's prices |
| `LLM_PRICE_OUTPUT_PER_MTOK` | `15.0` | USD per million output tokens |
| `ALLOW_PRIVATE_LLM_URLS` | `true` | `false` on a shared deployment: refuses base URLs that resolve to private or loopback addresses |
| `LLM_MAX_CONCURRENCY` | `16` | Model calls in flight per API process (not in `.env.example`) |
| `LLM_MAX_OUTPUT_TOKENS` | `4096` | Default output cap for a call that does not set one. The agent asks for 500 per step and the CRM note for 400 |
| `CALL_MAX_MODEL_CALLS`, `TURN_MAX_STEPS`, `CALL_MAX_TOKENS`, `CALL_MAX_COST_USD` | `80`, `6`, `200000`, `0.50` | Per-call and per-turn budgets (see *Prices and budgets*) |

The provider's model name is passed through unchanged. The agent needs a model that supports tool calling; the
connection test below sends a request without tools, so it does not prove this.

## Providers

| `LLM_PROVIDER` | Adapter | Endpoint | Key |
|---|---|---|---|
| `anthropic` | `backend/app/llm/anthropic.py` | `POST {base}/v1/messages` | `x-api-key` header |
| `openai_compat` | `backend/app/llm/openai_compat.py` | `POST {base}/chat/completions` | `Authorization: Bearer` when set |
| `ollama` | the same OpenAI-compatible adapter | `POST {base}/chat/completions` on Ollama's `/v1` | none |
| `stub` | `backend/app/llm/stub.py` with `backend/app/agent/stub.py` | none | none |

**OpenAI-compatible adapter** (`openai_compat.py`). Sends `stream: false`, the messages in the chat format, the tools
as functions, and `max_tokens`. Reads usage from `prompt_tokens`, `completion_tokens` and
`prompt_tokens_details.cached_tokens`; when a provider reports no usage, token counts are estimated from text length
and marked as estimates. Some gateways answer with a server-sent event stream even though `stream: false` was sent.
The adapter detects this (by content type or a leading `data:`) and folds the chunks into one reply, so both forms
are handled by the same code and `test_plain_and_streamed_responses_give_the_same_result` checks it. A tool call whose
arguments are not valid JSON is passed on as invalid and is reported to the model as an error, not raised.

**Anthropic adapter** (`anthropic.py`). Uses the Messages API with `anthropic-version: 2023-06-01`. The system prompt
and the last tool definition are marked with `cache_control: ephemeral`, so later steps of a call can read them from
the provider's cache. Tool results become user turns, as that API requires; results of parallel calls share one turn.
Usage is reported as input tokens including cache reads and writes, with cache reads counted separately so they can be
priced at the cached rate.

**Ollama.** Ollama serves an OpenAI-compatible endpoint under `/v1`. Use the OpenAI-compatible adapter's path through
`LLM_PROVIDER=ollama`. Ollama listens on `127.0.0.1` by default, so it must be configured to listen on an address the
API container can reach.

**Stub.** `LLM_PROVIDER=stub` runs `STUB_RESPONDER` (default `app.agent.stub:demo_responder`), a rule-based function
that reads the last customer turn and the tool results. It exists so the stack runs with no provider, for the browser
journeys and load runs. It is not evaluated and should not be read as a model.

## Retry, fallback and concurrency

`backend/app/llm/base.py::call_with_retry`:

- **Retried** (up to four attempts, exponential back-off from 0.5 s, capped at 30 s, with ±20% jitter, honouring
  `Retry-After`): timeouts, transport errors, HTTP `408`, `409`, `425`, `429`, `500`, `502`, `503`, `504`, `529`, and
  a response body that cannot be read.
- **Not retried** (raised at once): other client errors, such as `400`, `401`, `403`, `404` and `422`. Repeating them
  cannot succeed, and a wrong key is reported as such.
- **Fallback.** When the primary model is exhausted and a different fallback model is configured, the fallback gets one
  attempt, on the same provider.
- **Failure.** If that fails too, `LLMUnavailable` is raised.
- **Concurrency.** A semaphore of `LLM_MAX_CONCURRENCY` limits calls in flight in each process.

Known gap: `LLMUnavailable` is not caught on the customer-turn path (see `docs/ARCHITECTURE.md`). A model outage that
outlasts the retries ends the turn with an error rather than a spoken apology. The evaluation separates runs in which
the provider did not answer, so an outage is not scored as a model failure.

## Per-organisation settings

Administrators manage the organisation's model on the administration screen, or through the API:

| Route | Use |
|---|---|
| `GET /api/settings/llm` | Read the saved or environment settings. The key is never returned; `api_key_set` says whether one is stored |
| `PUT /api/settings/llm` | Save. Omit `api_key` to keep the stored key; send `""` to clear it |
| `POST /api/settings/llm/test` | Send one short request with the saved settings. Returns `ok`, the model's reply and the latency, or the provider's error text (with any key masked) |

Base URLs are checked when saved and again each time a client is built for an organisation that has one
(`factory.validate_base_url`). The check refuses a non-HTTP scheme, an unresolvable host, link-local and multicast
addresses (including the cloud metadata address), and, when `ALLOW_PRIVATE_LLM_URLS=false`, private and loopback
addresses. Because the host is resolved on each check, a base URL that resolves differently later is still refused.

**Keys are encrypted** (`backend/app/security/crypto.py`). The key is stored as a Fernet token whose key is the SHA-256
of `SECRET_KEY`. Two consequences:

- Set `SECRET_KEY` to a long random value before saving any key. The compose default is public and is refused for
  `COOKIE_SECURE=true` (the API will not start).
- Changing `SECRET_KEY` makes stored keys undecryptable. Organisations then fail their turns with an error until a key
  is saved again.

## Concrete setups

Each block is a `.env` fragment. Replace the placeholders; never commit real values.

### Anthropic

```bash
LLM_PROVIDER=anthropic
LLM_MODEL=<a model id from your Anthropic account>
LLM_API_KEY=<your Anthropic API key>
LLM_FALLBACK_MODEL=<optional: another model id>
LLM_PRICE_INPUT_PER_MTOK=<the input price for that model>
LLM_PRICE_OUTPUT_PER_MTOK=<the output price for that model>
```

### OpenAI

```bash
LLM_PROVIDER=openai_compat
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=<a model id from your OpenAI account>
LLM_API_KEY=<your OpenAI API key>
```

### Google Gemini (its OpenAI-compatible endpoint)

```bash
LLM_PROVIDER=openai_compat
LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
LLM_MODEL=<a Gemini model id>
LLM_API_KEY=<your Gemini API key>
```

### Groq

```bash
LLM_PROVIDER=openai_compat
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_MODEL=<a model id offered by Groq>
LLM_API_KEY=<your Groq API key>
```

### Any OpenAI-compatible gateway

The evaluation used a local gateway called 9Router, which listens on port 20128 on the host. A container reaches the
host through `host.docker.internal`, which `docker-compose.yml` maps to the host gateway for the `api` service.

```bash
LLM_PROVIDER=openai_compat
LLM_BASE_URL=http://host.docker.internal:20128/v1     # from the host itself: http://localhost:20128/v1
LLM_MODEL=<a route name the gateway serves>
LLM_API_KEY=<the gateway's key, if it checks one>
ALLOW_PRIVATE_LLM_URLS=true                           # the gateway is on a private address
```

The gateway's routes may stream their answers even when `stream: false` is sent; the adapter handles both. The
evaluation scripts read the same gateway from `NINEROUTER_BASE_URL` and `NINEROUTER_API_KEY` (in `../.env.local`,
outside this repository, which the Makefile loads); `backend/eval/common.py::configure_model` overrides the
organisation's settings for the evaluation run.

### Ollama on the host

```bash
LLM_PROVIDER=ollama
LLM_BASE_URL=http://host.docker.internal:11434/v1     # from the host itself: http://localhost:11434/v1
LLM_MODEL=<a model you have pulled into Ollama>
```

## Speech

Speech has two directions, each with a `local` and a hosted provider. The two are independent.

| Direction | Variables | Local | Hosted |
|---|---|---|---|
| Recognition | `STT_PROVIDER`, `STT_MODEL`, `STT_DEVICE`, `STT_COMPUTE_TYPE`, `STT_BASE_URL`, `STT_API_KEY` | faster-whisper in the API process | `POST {STT_BASE_URL}/audio/transcriptions` |
| Synthesis | `TTS_PROVIDER`, `TTS_VOICE`, `TTS_MODEL`, `TTS_BASE_URL`, `TTS_API_KEY` | Piper, one ONNX voice file | `POST {TTS_BASE_URL}/audio/speech` |

Two defaults are local names and must be changed when a hosted provider is chosen: `STT_MODEL` (`base.en`) and
`TTS_VOICE` (`en_US-lessac-medium`) are sent to the hosted service as they are.

### Local recognition (faster-whisper)

`backend/app/speech/stt.py::LocalTranscriber` loads `WhisperModel` once per process. It looks for the model in
`$MODELS_DIR/whisper/<STT_MODEL>` (default `/models`) and falls back to downloading the name from Hugging Face when the
directory is missing. Recognition uses beam size 1, English, and an initial prompt of account and service words, so
recognition favours them.

| Image | Models baked in | Typical settings |
|---|---|---|
| `app` (the default build) | `base.en` | `STT_MODEL=base.en`, `STT_DEVICE=cpu`, `STT_COMPUTE_TYPE=int8` |
| `gpu` (with `docker-compose.gpu.yml`) | `base.en` and `small.en` | `STT_MODEL=small.en`, `STT_DEVICE=cuda`, `STT_COMPUTE_TYPE=float16` |

`tiny.en` is listed in `.env.example` but is not baked into either image. Choosing it makes the first call download it,
which needs network access and waits for the download.

**GPU.** Use both compose files:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build api
```

The file asks for `nvidia.com/gpu=all`, which needs the NVIDIA Container Toolkit with CDI enabled; `docker info` lists
the devices when it is set up. The `gpu` target of `backend/Dockerfile` builds on the `app` target and adds the CUDA
runtime libraries for CTranslate2 (`nvidia-cublas-cu12`, `nvidia-cudnn-cu12`) and the `small.en` model. The library
path is set in the image. Other GPUs need CUDA libraries that match the CTranslate2 build; the compose file does not
select a GPU model.

Recognitions are serialised within a process (one at a time). A recognition's wait is reported as `stt_wait_ms`, so
concurrent calls show their queueing in the latency panel. See `docs/SCALE.md` for measured behaviour.

### Hosted recognition (OpenAI-compatible)

```bash
STT_PROVIDER=openai_compat
STT_BASE_URL=https://api.groq.com/openai/v1           # or https://api.openai.com/v1
STT_MODEL=whisper-large-v3                            # the hosted model name
STT_API_KEY=<your key for that service>
```

The audio is sent as a 16 kHz mono WAV file with language `en`, with a 30-second timeout. Audio leaves the deployment
on this path. `stt_wait_ms` is 0 because the request does not queue behind the local model.

### Local synthesis (Piper)

`backend/app/speech/tts.py::LocalSynthesizer` loads `$MODELS_DIR/piper/<TTS_VOICE>.onnx`, which needs its
`.onnx.json` configuration next to it. The image downloads two voices at build time (`en_US-lessac-medium`, the
default, and `en_US-ryan-medium`, which the evaluation uses for the customer's voice). Each sentence is synthesised
on its own, in a worker thread, and the sample rate comes from the voice's configuration.

**Adding a voice** to the image: add its name to the `python -m piper.download_voices --data-dir /models/piper …` line
in `backend/Dockerfile`, rebuild the API image (`docker compose build api`), and set `TTS_VOICE` to the voice name
(without `.onnx`).

### Hosted synthesis (OpenAI-compatible)

```bash
TTS_PROVIDER=openai_compat
TTS_BASE_URL=https://api.openai.com/v1
TTS_MODEL=tts-1                                       # the default when left empty
TTS_VOICE=<a voice the provider offers>
TTS_API_KEY=<your key for that service>
```

The request asks for raw PCM (`response_format: pcm`), which is 16-bit mono at 24 kHz; the audio message sent to the
browser carries that rate. The timeout is 30 seconds. Text leaves the deployment on this path.

## Prices and budgets

Costs are estimates from the prices in configuration (per organisation, or the environment's
`LLM_PRICE_*`). `backend/app/llm/pricing.py::cost_usd` multiplies fresh input tokens by the input price, cached input by
one tenth of it, and output tokens by the output price. The figures are stored on each call (`cost_usd`, `tokens`,
`model_calls`).

| Budget | Setting | Checked |
|---|---|---|
| Model calls for one customer turn | `TURN_MAX_STEPS` | At the start of each model step; reaching it hands the call to a person |
| Model calls for the call | `CALL_MAX_MODEL_CALLS` | As above |
| Tokens for the call | `CALL_MAX_TOKENS` | As above |
| Estimated cost for the call | `CALL_MAX_COST_USD` | As above |
| Calls in progress for an organisation | `ORG_MAX_LIVE_CALLS` | When a call starts |

`ORG_DAILY_COST_USD` and `GLOBAL_DAILY_COST_USD` are set in `.env.example` and passed through compose, but no code
enforces them. They do not stop spending today. Until they are enforced, the per-call limits and the provider's own
spending limits are the only controls on cost.

## Testing a configuration

| Check | How |
|---|---|
| The saved model answers | `POST /api/settings/llm/test`, or the test button on the administration screen |
| Gateway models return a tool call | `make test-live` (tests marked `live`; they need the gateway settings in `../.env.local` and skip without them) |
| Speech models work | `make test-speech` (runs the speech tests in the test image, which has the models) |
| Recognition accuracy | `make eval-wer` (word error rate of the recogniser in `STT_*`, on synthesised speech) |
| The agent with a model | `make eval-agent SPLIT=dev MODEL=<route>` (scripted calls, graded from the database). Results: `docs/EVALUATION.md` |

`make eval-agent` and the other `eval-*` targets run inside the test image and read `../.env.local`; they set the
gateway from `NINEROUTER_*` and override the model for the run, so the organisation's saved settings do not apply.
