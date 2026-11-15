# API

Every HTTP route, the voice WebSocket and the two event streams. Routes are listed by the module that defines them
in `backend/app/api/`; `backend/app/main.py` mounts them. The interactive reference is at `/docs` on the API
(`http://localhost:8400/docs` with the default compose file).

## Conventions

**Base and paths.** Browsers call the API through nginx on the same origin, so paths are relative (`/api/...`).

**Sessions.** Signing in (`POST /api/auth/login` or `signup`) sets the cookie `voiceops_session`: HttpOnly,
`SameSite=Lax`, `Secure` only when `COOKIE_SECURE=true`, and valid for `SESSION_HOURS` (12 by default). The server keeps
only a SHA-256 hash of the token. Sign-out, deactivation and a password change end sessions on the server at once.

**CSRF.** Every request that is not `GET`, `HEAD` or `OPTIONS` to a route that needs a signed-in user must send the
header `X-CSRF-Token` with the value returned by the sign-in, sign-up or `GET /api/auth/me` response. A missing or
wrong value gets `403`. Sign-in and sign-up do not need it.

**Roles.** Four roles, stored on the user: `viewer`, `agent`, `supervisor`, `admin`. The tables below use these labels:

| Label | Who |
|---|---|
| any signed-in | any of the four roles, in the caller's organisation |
| staff | `agent`, `supervisor`, `admin` |
| supervisor | `supervisor`, `admin` |
| admin | `admin` |
| caller | the signed-in person who started the call (`started_by`) |

**Organisations.** Every query runs inside the caller's organisation. An id that belongs to another organisation
gets `404` (or, for the voice socket, close code `4404`). The same answer is given for "does not exist" and "belongs
to someone else".

**Errors.** Errors are `{"detail": ...}`. Most `detail` values are strings. Request validation failures (`422`)
carry FastAPI's list form: `{"detail": [{"loc": [...], "msg": "...", "type": "..."}]}`. The web client shows the first
message.

| Status | Meaning here |
|---|---|
| `401` | Not signed in, or the sign-in failed (`"Incorrect e-mail or password."`, the same text for an unknown e-mail) |
| `403` | Signed in, but the role or the call's rules do not allow it; or a missing CSRF token |
| `404` | Not found in the caller's organisation |
| `409` | State conflict: call already ended, credit already decided, someone else holds the call, call busy |
| `422` | Invalid input (weak password, bad e-mail, a credit amount that is not a number, a missing reason) |
| `429` | Rate limit, or the organisation's live-call limit (`Retry-After` on the live-call case) |
| `503` | The database connection pool is exhausted (`Retry-After: 5`), or Redis is unavailable for rate limiting or readiness |

**Rate limits** (sliding window, in Redis):

| Route | Limit | Keyed by |
|---|---|---|
| `POST /api/auth/login` | 5 per minute per e-mail; 30 per minute per client address | e-mail, then address |
| `POST /api/auth/signup` | 10 per hour per client address (and `ALLOW_SIGNUP` must be true) | address |
| `POST /api/calls` | `CALLS_PER_MINUTE` (10) per minute | see note below |
| `POST /api/settings/llm/test` | 6 per minute | see note below |

The client address is `X-Forwarded-For` when `TRUSTED_PROXY=true` (the compose default; nginx overwrites that header),
otherwise the socket address.

The limiter resolves the session cookie itself, so a signed-in person's limit is theirs whatever address they use.

**Security headers** on every response: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
`Referrer-Policy: no-referrer`, `Permissions-Policy`, and a `Content-Security-Policy` of
`default-src 'none'; frame-ancestors 'none'` (except on `/docs`, `/redoc` and `/openapi.json`). Under `/api/`,
`Cache-Control: no-store`. With `COOKIE_SECURE=true`, `Strict-Transport-Security`.

**Request ids.** Each response carries `X-Request-ID`. A request may send its own (up to 64 characters); the id is
written to the JSON log line for the request.

**CORS.** Origins come from `CORS_ORIGINS`. Credentials are allowed. Allowed headers are `Content-Type`,
`X-CSRF-Token`, `X-Request-ID` and `Last-Event-ID`.

**Pagination.** Lists are capped, not paged, except the audit log, which pages by id.

**Money** is returned as a string with two decimal places (`"10.00"`).

**Timestamps** are ISO 8601 strings.

## Health and metrics

| Method and path | Who | Does | Notes |
|---|---|---|---|
| `GET /healthz` | anyone | `{"status": "ok"}` while the process runs | `backend/app/api/health.py` |
| `GET /readyz` | anyone | `{"status": "ready"}`, or `503` with `"failing": ["database" and/or "redis"]` | Opens a new PostgreSQL connection and pings Redis, each with a 2 s timeout |
| `GET /metrics` | anyone, or a bearer token when `METRICS_TOKEN` is set | Prometheus text: HTTP request durations by route template and status, and gauges for run, token and cost totals | `backend/app/obs/metrics.py`. Known defect: the gauge query reads a table, `runs`, that no migration creates, so the endpoint answers with a server error and the gauges are not produced. Wrong or missing bearer token: `401` |

## Auth

Prefix `/api/auth`, `backend/app/api/auth.py`.

| Method and path | Who | Does | Body | Notable errors |
|---|---|---|---|---|
| `POST /api/auth/signup` | anyone | Creates an organisation and its first `admin`; signs them in | `email`, `password`, `name` (1–100), `org_name` (2–100) | `403` sign-up disabled; `409` e-mail in use; `422` weak password (the reason is in `detail`) or bad e-mail; `429` |
| `POST /api/auth/login` | anyone | Signs in; sets the cookie | `email`, `password` | `401` bad credentials; `429` |
| `POST /api/auth/logout` | any signed-in | Ends this session on the server and clears the cookie | none | `403` CSRF; returns `204` |
| `GET /api/auth/me` | any signed-in | The current user and CSRF token | none | `401` |
| `POST /api/auth/password` | any signed-in | Changes the password and signs out the user's other sessions | `current_password`, `new_password` | `403` wrong current password; `422` weak password; returns `204` |

Sign-up and sign-in responses: `{"user": {id, org_id, email, name, role}, "csrf_token": "..."}`.

## Users

Prefix `/api/users`, `backend/app/api/users.py`. All routes: **admin**.

| Method and path | Does | Body | Notable errors |
|---|---|---|---|
| `GET /api/users` | Lists the organisation's users | none | |
| `POST /api/users` | Creates a user in the caller's organisation (`201`) | `email`, `name` (1–100), `role` (`viewer`, `agent`, `supervisor`, `admin`), `password` | `409` e-mail in use (across all organisations); `422` weak password |
| `PATCH /api/users/{user_id}` | Changes name, role or active state; deactivating ends the user's sessions | any of `name`, `role`, `is_active` | `404` (also for a user of another organisation); `409` the organisation must keep one active administrator |

## Audit

`GET /api/audit`, **admin**, `backend/app/api/audit.py`. Query: `limit` (1–200, default 50), `before` (an id from 1 up to
2^63−1; return entries with an id below this; anything else is `422`), `action` (exact action or a prefix such as `user.`). Returns
`{"entries": [{id, at, user, action, target, detail, ip}], "next_before": id or null}`. The log is append-only for the
application role (see `docs/DATABASE.md`).

## Model settings

Prefix `/api/settings`, `backend/app/api/settings.py`. **admin** for all three routes.

| Method and path | Does | Body | Notable errors |
|---|---|---|---|
| `GET /api/settings/llm` | The organisation's saved model settings, or the environment's if none are saved | none | |
| `PUT /api/settings/llm` | Saves them; the API key is write-only | `provider` (`openai_compat`, `anthropic`, `ollama`, `stub`), `model` (1–120), `base_url` (up to 300), `api_key` (omit to keep the stored key; `""` clears it), `fallback_model`, `price_input_per_mtok`, `price_output_per_mtok` (0–1000) | `422` an `openai_compat` provider without a base URL; `422` a base URL the server refuses (scheme, unresolvable host, link-local or multicast address, or a private address when `ALLOW_PRIVATE_LLM_URLS=false`) |
| `POST /api/settings/llm/test` | Sends one tiny request with the saved settings | none | Returns `{"ok": true, "model", "latency_ms", "reply"}` or `{"ok": false, "error"}`; `429` |

`GET` returns `provider`, `model`, `base_url`, `fallback_model`, `price_input_per_mtok`, `price_output_per_mtok`,
`api_key_set` (boolean) and `source` (`organisation` or `environment`). The key itself is never returned.

## Call settings

Prefix `/api/call-settings`, `backend/app/api/call_settings.py`.

| Method and path | Who | Does | Body |
|---|---|---|---|
| `GET /api/call-settings` | any signed-in | `{"credit_limit": "10.00"}`: the credit the agent may apply on one call without a supervisor | none |
| `PUT /api/call-settings` | admin | Sets it | `credit_limit`: 0 to 500, at most two decimal places |

## Policies (knowledge)

Prefix `/api/knowledge`, `backend/app/api/knowledge.py`.

| Method and path | Who | Does | Body or query | Notable errors |
|---|---|---|---|---|
| `GET /api/knowledge` | any signed-in | Lists documents: `slug`, `title`, `updated_at` | none | |
| `GET /api/knowledge/search` | any signed-in | Searches passages; returns the top 5 with `citation`, `title`, `heading`, `body`, `rank` | `q` (2–500 characters) | |
| `GET /api/knowledge/{slug}` | any signed-in | One document's full text | none | `404` |
| `PUT /api/knowledge/{slug}` | admin | Creates or replaces a document and rebuilds its passages | `title` (1–200), `body` (10–100,000 characters) with sections written `## n. Heading` | `422` slug not lower-case letters, digits and hyphens (up to 60 characters); `422` no section headings |

Passages are built from the `## n. Heading` sections. The citation of a passage is `[slug §n]`.

## Customers

Prefix `/api/customers`, `backend/app/api/customers.py`. **staff**.

| Method and path | Does | Query | Notes |
|---|---|---|---|
| `GET /api/customers` | Up to 50 customers by name | `q`: matches name, account number or phone (up to 100 characters) | Returns `id`, `name`, `account_number`, `postcode` |
| `GET /api/customers/{customer_id}` | One customer: contact details, `vulnerable` flag, services, the latest 12 bills, 20 tickets, 20 credits and 20 calls where this customer was verified | none | `404` |

## Calls

Prefix `/api/calls`, `backend/app/api/calls.py`. The call-state values are `live`, `handed_off` and `ended`.

| Method and path | Who | Does | Body or query | Notable errors |
|---|---|---|---|---|
| `POST /api/calls` | any signed-in | Starts a call; the greeting is in the response (`201`) | `channel`: `voice` or `text` (default `text`) | `429` the organisation has `ORG_MAX_LIVE_CALLS` calls not ended (`Retry-After: 30`), or the per-minute limit |
| `GET /api/calls` | any signed-in | Lists the organisation's calls, newest first | `status`: `open` (not ended), `live`, `handed_off` or `ended`; `limit` (1–500, default 100) | |
| `GET /api/calls/live/events` | any signed-in | Server-Sent Events for the organisation's calls | `Last-Event-ID` header | See *Server-Sent Events* |
| `GET /api/calls/{call_id}` | any signed-in | The call, its customer (if verified: name and account number), turns, events and credits | none | `404` |
| `GET /api/calls/{call_id}/events` | any signed-in | Server-Sent Events for one call | `Last-Event-ID` header | `404` |
| `POST /api/calls/{call_id}/turns` | caller | A typed customer turn; returns what the agent would say, without speaking it | `text` (1–2000) | `403` not the caller; `409` ended, or the call is busy after 60 s |
| `POST /api/calls/{call_id}/take-over` | staff | A person takes the call; the agent stops answering | none | `409` ended, or another person already took it |
| `POST /api/calls/{call_id}/reply` | staff | The person who took the call says something to the customer | `text` (1–2000) | `409` the call is not `handed_off` to this person |
| `POST /api/calls/{call_id}/end` | caller, the person who took it, or supervisor | Ends the call and writes the CRM note | none | `403` |
| `GET /api/calls/{call_id}/latency` | any signed-in | Each turn's timings, by index | none | |

Call object (returned by `POST` and `GET` list; `GET` by id adds `turns`, `events`, `credits`, `customer_account`):

```json
{
  "id": "uuid", "status": "live", "channel": "voice",
  "started_at": "...", "ended_at": null,
  "verified": true, "customer": "Amelia Hart", "handled_by": null,
  "handed_off_reason": null, "summary": null,
  "model_calls": 4, "cost_usd": 0.0123
}
```

`POST /api/calls` also returns `"greeting": "Hello, you're through to ...".`

`GET /api/calls/{call_id}` returns `turns` as `{idx, speaker, text, interrupted, timings, at}` where `speaker` is
`customer`, `agent` or `person`; `events` as `{kind, data, at}`; and `credits` as `{id, amount, status, reason}`.

`POST /api/calls/{call_id}/end` returns the CRM note: `reason`, `outcome`, `follow_up`, `sentiment`, `written_by`
(`model` or `system`), and `unsupported` (sentences removed because they carried a figure not found in the call).

`POST /api/calls/{call_id}/turns` returns `{reply, status, waiting, timings, customer_idx, agent_idx}`. `waiting` is the
pending approval when the graph is paused, otherwise `null`. It is the API counterpart of the voice path; it does not
synthesise speech.

## Credits

Prefix `/api/credits`, `backend/app/api/credits.py`.

| Method and path | Who | Does | Body or query | Notable errors |
|---|---|---|---|---|
| `GET /api/credits` | staff | Credits with the given status, oldest first, up to 500 | `status`: `pending` (default), `applied` or `refused` | |
| `POST /api/credits/{credit_id}/decide` | supervisor | Approves or refuses a credit | `decision` (`approved` or `refused`), `reason` (up to 500; required for a refusal) | `404`; `409` already decided; `403` the decider was on the call (started it or took it over); `422` refusal without a reason |

A list entry carries `id`, `amount`, `reason`, `status`, `customer`, `account_number`, `call_id`, `call_status`,
`requested_at`, `decided_at` and `decision_reason`.

`decide` returns `{"id", "status": "applied" or "refused", "agent_said"}`. `agent_said` is what the agent says next
when the call is still `live` and waiting on this decision; otherwise it is empty. A decision on a call that has ended
is recorded, and the agent does not speak it.

## Evaluation results

`GET /api/eval/results`, any signed-in, `backend/app/api/evaluation.py`. Reads the JSON files in
`backend/eval/results/` and returns them in groups: `results` (scripted-call runs), `attacks`, `unavailable` (runs in
which the model provider did not answer, shown apart so an outage is not read as a score), `retrieval` and `wer`. It
runs no model. The figures are in `docs/EVALUATION.md`.

## The voice socket

`ws(s)://<host>/api/voice/{call_id}`, `backend/app/api/voice.py`. The browser opens it after `POST /api/calls`.

### Handshake

The server checks, in order, and closes before accepting when a check fails:

| Check | On failure |
|---|---|
| If an `Origin` header is sent, it is one of `CORS_ORIGINS` | close `4403` "origin not allowed" |
| The session cookie resolves to a signed-in user | close `4401` "not signed in" |
| The call exists in the user's organisation | close `4404` "call not found" (the same for another organisation's call) |
| The user started the call, and it has not ended | close `4403` "not your call, or it has ended" |

A request with no `Origin` header is accepted if the cookie is valid. Browsers always send `Origin` on WebSocket
handshakes, so this matters only for non-browser clients.

After the handshake, if the call has only its greeting, the greeting is synthesised and sent; then the server sends
`{"type": "state", "state": "listening"}`.

### Client to server

| Message | Meaning |
|---|---|
| Binary frame | Audio: 16-bit little-endian PCM, mono, 16,000 samples per second. The browser sends 320-sample frames (640 bytes). A frame larger than 64 KiB (65,536 bytes), or with an odd number of bytes, is dropped without a message. Audio arriving more than two seconds faster than real time is dropped. |
| Text, `{"type": "end_turn"}` | Press to talk: the caller let go of the button, so the turn in progress ends now (no silence is needed). |
| Text, `{"type": "text", "text": "..."}` | A typed customer turn. The text is trimmed and cut to 2000 characters; empty text is ignored. Text frames over 8000 characters are ignored. |
| Text, `{"type": "end"}` | Ends the call (`service.end_call`), then the server sends `state: ended` and closes the socket normally. |

Any other message is ignored: a text frame that is not a JSON object (a number, an array, text that is not JSON, or
more than 8000 characters) is dropped, and the socket stays open.

### Server to client

| Message | Fields | When |
|---|---|---|
| `{"type": "state", "state": S}` | `S` is `listening`, `thinking`, `speaking`, `handed_off` or `ended` | At each change of phase; after each turn with the call's status |
| `{"type": "transcript", "text", "cut"}` | What the customer said; `cut` is true when the turn was cut at the maximum length | After recognition, for spoken turns only |
| `{"type": "agent_text", "text", "speaker"}` | The text being spoken; `speaker` is `agent` or `person` | Before the audio of that reply |
| `{"type": "audio", "rate", "seq"}` | Announces the next sentence's audio. `rate` is the sample rate of the following binary frames (the Piper voice's rate, or 24000 for hosted speech) | Once per sentence |
| binary | 16-bit little-endian PCM, mono, at the announced `rate`, in frames of at most 8192 bytes | After each `audio` message |
| `{"type": "audio_end"}` | The sentence sequence of one reply is complete | After the last sentence of a reply |
| `{"type": "clear"}` | Drop queued audio: the customer spoke over the agent | Barge-in |
| `{"type": "latency", ...}` | The turn's timings in milliseconds: `audio_ms`, `stt_ms`, `stt_wait_ms`, `agent_ms`, `tts_first_ms`, `first_audio_ms` (end of the customer's speech to the first sound back), `reply_ready_ms`; a typed turn carries `"input": "typed"` | After each turn |

A reply that was superseded by barge-in while the agent was still thinking is stored, not spoken; the socket sends
no audio for it.

### Close codes and timing

| Code | Meaning |
|---|---|
| `4401` | Not signed in |
| `4403` | Origin not allowed; or not the caller's call; or the call has ended |
| `4404` | Call not found in this organisation |

The server closes the socket after **300 seconds** with no message from the client (`IDLE_SECONDS`). A browser with the
microphone on sends frames continuously, so the timeout applies to text-only sessions and to sessions with the
microphone muted (the mute stops frames from being sent).

## Server-Sent Events

Two streams, served by `backend/app/calls/events.py` and routed in `backend/app/api/calls.py`:

| Stream | Path | Carries |
|---|---|---|
| Organisation | `GET /api/calls/live/events` | `call_started`, `call_state`, `call_ended`, `turn`, `approval_needed` |
| Call | `GET /api/calls/{call_id}/events` | All of the above for that call, plus `turn_interrupted` |

Frame format: `id: <Redis stream id>`, `event: <type>`, `data: <JSON>`. The stream starts with `retry: 2000`. A
comment line `: keep-alive` is sent after 15 seconds without an event. The server ends the response after 1800 seconds;
the browser reconnects.

Event data (each includes `call_id`):

| Event | Data |
|---|---|
| `call_started` | `channel` |
| `turn` | `turn_id`, `idx`, `speaker` (`customer`, `agent` or `person`), `text`, `timings` |
| `turn_interrupted` | `idx`, `spoken` (what was actually said aloud before barge-in) |
| `approval_needed` | `kind` (`credit_approval`), `credit_id`, `amount` |
| `call_state` | `status` (`handed_off` after a take-over, with `handled_by`) |
| `call_ended` | `summary` (the CRM note) |

**Resumption.** The browser sends `Last-Event-ID` on reconnect, and the server resumes after that stream id. If the
header is missing or not a Redis stream id, the server sends the whole retained stream from the beginning (about 2,000
entries, kept for 24 hours). Events the stream no longer holds are not replayed; the stored turns and events are
available from `GET /api/calls/{call_id}`.

Event types emitted to the browser by the live pages are `turn`, `turn_interrupted`, `call_state`, `call_ended` and
`approval_needed` for a call, and `call_started`, `call_state`, `call_ended` and `approval_needed` for the organisation.

## Who may call what

| Route | viewer | agent | supervisor | admin |
|---|:---:|:---:|:---:|:---:|
| `POST /api/auth/logout`, `GET /api/auth/me`, `POST /api/auth/password` | yes | yes | yes | yes |
| `GET /api/call-settings`, `GET /api/knowledge*`, `GET /api/eval/results` | yes | yes | yes | yes |
| `POST /api/calls`, `GET /api/calls`, `GET /api/calls/{id}`, `GET …/events`, `GET …/latency`, `GET /api/calls/live/events` | yes | yes | yes | yes |
| `POST /api/calls/{id}/turns` (the caller only) | yes | yes | yes | yes |
| `POST /api/calls/{id}/end` (every role may call it; only the caller, the handler or a supervisor succeeds) | yes | yes | yes | yes |
| `GET /api/customers*`, `GET /api/credits`, `POST /api/calls/{id}/take-over`, `POST /api/calls/{id}/reply` | | yes | yes | yes |
| `POST /api/credits/{id}/decide` | | | yes | yes |
| `PUT /api/call-settings`, `PUT /api/knowledge/{slug}`, `GET`/`PUT /api/settings/llm`, `POST /api/settings/llm/test`, `/api/users*`, `GET /api/audit` | | | | yes |
| `POST /api/auth/signup`, `POST /api/auth/login`, `GET /healthz`, `GET /readyz`, `GET /metrics` | public | public | public | public |

Read access to call transcripts is not limited to staff: any signed-in user of the organisation, including a
`viewer`, can read any call's turns and events. This is how the code is written; `docs/SECURITY.md` does not list it
as a control. The voice socket, by contrast, admits only the person who started the call.
