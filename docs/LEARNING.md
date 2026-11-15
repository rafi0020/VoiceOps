# Learning the code

A guided read for an engineer joining the project. It follows one spoken turn from the microphone to the speaker,
then the supervisor's decision on a credit, a take-over, the end of the call, and the evaluation harness. Each stop
names the files and functions to read, what to notice, and the tests that show the behaviour. Test names are real;
run one with `cd backend && uv run pytest tests/test_x.py::test_name -q`, and an end-to-end journey with
`cd frontend && npx playwright test e2e/calls.spec.ts -g "name"`.

Read `docs/ARCHITECTURE.md` first; this guide assumes its vocabulary (turn, phase, thread, interrupt, hand-off).

## Before you start

```bash
make dev-up                  # PostgreSQL (55462), PgBouncer (56462) and Redis (56409) in containers
cd backend && uv sync        # Python 3.13
make test                    # backend tests with RUN_LIVE=0; needs the three services above
```

The tests connect to PostgreSQL directly on port 55462, not through PgBouncer, by the defaults in
`backend/tests/conftest.py`. They rebuild `voiceops_test` from the migrations at the start of each run.

Three facts make the rest of the reading easier:

- **Tenancy is in the database.** `backend/app/db.py::tenant_session(org_id)` sets the organisation for one
  transaction, and row-level security decides what every query sees (`backend/app/rls.py::enable_rls`). Read
  `tests/test_tenant_isolation.py::test_rows_of_one_org_are_invisible_to_another` and
  `test_org_does_not_leak_between_transactions_on_a_pooled_connection` before you write a query.
- **The model never supplies identity.** Account tools take no customer id. They act on the call's
  `verified_customer_id`, which only `verify_identity` sets, on the server. The prompt explains the rules; the code
  enforces them.
- **One turn per call at a time.** A Redis lock serialises turns for a call across processes
  (`backend/app/calls/service.py::call_lock`). Keep it in mind every time you see a turn start.

---

## Stop 1. The microphone

**Read**

- `frontend/public/capture-worklet.js`: `Capture.process`. Samples are averaged over each output sample's input window
  (a box filter), converted to 16-bit, and posted as 320-sample frames (20 ms at 16 kHz).
- `frontend/src/app/(app)/call/page.tsx`: `start` (creates the `AudioContext` on the click, then the call, then the
  socket), `startMic` (`getUserMedia` with echo cancellation, noise suppression and automatic gain; loads the worklet;
  connects the microphone to it; sends each posted frame on the socket unless muted).
- The same file's `Player` class: plays each binary frame as an `AudioBuffer` scheduled back to back; `clear` stops
  everything queued.

**Notice**

- The browser decides the sample rate of its own context. The worklet resamples to 16 kHz, so the server never sees
  anything else.
- Muting stops frames from being sent; it does not close the socket. The server closes an idle socket after five
  minutes, so a long mute ends the session (`docs/API.md`, *Close codes and timing*).
- `Player` plays what the server sends; it does not know about turns.

**Tests**

- `frontend/e2e/calls.spec.ts`: "a typed call checks who the caller is, finds the outage and ends with a note" exercises
  the same socket and turn path with typed text, which runs without a microphone.
- `backend/tests/test_voice.py::test_a_spoken_turn_is_recognised_answered_spoken_and_timed` sends recorded audio through
  the real session, recognition and synthesis (marked `speech`; run with `make test-speech`).

## Stop 2. The voice socket

**Read**

- `backend/app/api/voice.py`: `voice` and its constants `MAX_FRAME` and `IDLE_SECONDS`.
- `backend/app/main.py`: where the router is mounted, and the CORS middleware, which does not cover WebSockets.

**Notice**

- The handshake checks come before `accept`: the Origin header (required), the session cookie, the call's
  ownership and that it has not ended. The close codes are in `docs/API.md`.
- Frames over 64 KiB, or with an odd number of bytes, are dropped. A text frame must be a JSON object;
  `{"type": "text"}` is a typed turn, `{"type": "end_turn"}` ends a press-to-talk turn and `{"type": "end"}` ends the
  call. Anything else is ignored (`parse_command`, `audio_frame_ok` in `api/voice.py`).
- The greeting is queued as speech, so the receive loop starts at once and the greeting can be spoken over.
- The page sends `{"type": "ping"}` every minute so a muted caller's socket is not closed as idle; a socket that
  closes without "end" ends the call.

**Tests**

- `backend/tests/test_security_basics.py::test_a_voice_socket_without_an_origin_header_is_refused` covers the Origin
  check; the other close codes (4401, 4403, 4404) have no test. Add one before you change them.

## Stop 3. The session: turns, barge-in and chaining

**Read**

- `backend/app/voice/session.py`: `on_audio`, `on_text`, `_queue`, `barge_in`, `_audible`, `_stop_speaking`,
  `_respond`, `_release_held`, `_speak`, `_play_out`, and `_follow_people`.

**Notice**

- Audio goes out much faster than it plays, so "is the agent speaking?" is answered by a playback clock
  (`playing["until"]`), not by whether a task is still sending. This was the final review's one critical finding: the
  first version stopped counting as "speaking" once the last byte was sent, so barge-in worked only for the first
  second of a reply.
- `_queue` chains answers with `asyncio.wait` on the previous task, so cancelling a queued task really cancels it; a
  failure inside a turn is logged and apologised for, and the session listens again.
- `_respond` speaks a reply only if no newer turn has been queued and the caller is not speaking at that moment;
  otherwise it is stored as not spoken, or held until the sound fades (`_release_held`).
- Timings are saved in a shielded `finally`, so a caller who speaks over the reply does not lose the turn's latency.

**Tests**

- `backend/tests/test_voice_session.py` drives the session with the real call service and a scripted model but fake
  speech that is instant, as real synthesis nearly is: speaking over after all audio was sent, a caller who pauses
  mid-sentence, a cough while the agent thinks, a supervisor's decision heard on the call, a take-over mid-answer, a
  failed turn, and queued speech cancelled.
- `backend/tests/test_voice.py` runs the real models (in the test image) for recognition, synthesis and barge-in.

## Stop 4. Finding a turn in the audio

**Read**

- `backend/app/speech/vad.py`: `TurnDetector.feed_float`, `_finish`, the constants `WINDOW`, `START`, `END`, `PRE_ROLL`,
  and `probability`.
- `backend/app/speech/audio.py`: `pcm16_to_float`.

**Notice**

- Silero VAD runs on 512-sample windows with its state carried across windows, so each piece of audio is judged once.
- Hysteresis: a turn starts above 0.5 and continues above 0.35.
- A 320 ms pre-roll is kept so the first syllable is not lost.
- A turn ends after `VAD_SILENCE_MS` of silence. Speech shorter than `VAD_MIN_SPEECH_MS` is not a turn. The closing
  silence is removed before recognition, because it only slowed the recogniser.
- A turn longer than `MAX_TURN_SECONDS` is cut and handed on, so recognition never waits on an unbounded buffer.

**Tests**

- `backend/tests/test_speech.py::test_a_turn_is_found_between_silences_and_noise_is_not_a_turn`
- `backend/tests/test_speech.py::test_a_monologue_is_cut_at_the_maximum_turn_length`
- `backend/tests/test_voice.py::test_noise_and_silence_are_not_turns`

## Stop 5. Recognition

**Read**

- `backend/app/speech/stt.py`: `LocalTranscriber` (the lock, `_run`, `transcribe`), `HostedTranscriber`, `transcriber()`.
- `backend/app/voice/session.py`: `is_noise` and `_audio_turn`, which drops what Whisper invents from breath and noise
  (a phrase such as "thank you." counts as noise only when the turn is very short or quiet).

**Notice**

- One model per process. Recognitions take a lock, so they run one at a time, and the wait is reported as
  `stt_wait_ms`. A concurrency problem shows up as that number before it shows up anywhere else.
- The hosted variant posts a WAV file to `/audio/transcriptions`; its wait is 0 because it does not queue locally.

**Tests**

- `backend/tests/test_speech.py::test_the_recogniser_hears_what_was_said`
- `backend/tests/test_speech.py::test_citations_are_kept_in_text_but_not_spoken_and_replies_split_into_sentences`
  covers the text side of the output path.

## Stop 6. A customer turn: the call service

**Read**

- `backend/app/calls/service.py`: `call_lock`, `customer_turn`, `add_turn`, and `load`.
- `backend/app/api/calls.py`: `say` (the typed REST route; the socket reaches the same service).

**Notice**

- `customer_turn` locks the call, refuses an ended call, stores the customer's turn, and then branches: a
  `handed_off` call returns no reply; a graph paused for approval returns the fixed "still waiting" sentence without
  starting a new run; otherwise `run_turn` runs.
- The status is read again after the run, and a `call_state` event is published only if it changed.
- `add_turn` assigns the next index and publishes a `turn` event to both streams. The Live screen and the call screen
  see the same turns.

**Tests**

- `backend/tests/test_calls_api.py::test_a_typed_call_verifies_reads_a_bill_and_ends_with_a_note` runs the typed path
  through the service, the graph and the stub model, then checks the stored turns, the events and the note.
- `frontend/e2e/calls.spec.ts`: "a typed call checks who the caller is, finds the outage and ends with a note".

## Stop 7. The graph

**Read**

- `backend/app/agent/graph.py`: `CallState`, `agent`, `tools`, `approval`, `after_agent`, `after_tools`, `build_graph`,
  `run_turn`, `resume`, `_config`.
- `backend/app/agent/checkpoint.py`: `checkpointer`, `create_tables`.

**Notice**

- The thread id is the call id (`_config`). Each call has its own checkpoints, and any process can resume one.
- `agent` checks four budgets before calling the model. When one is reached it calls `hand_off` itself and returns a
  fixed apology. The model is not asked again.
- `tools` runs every tool call the model asked for, in order. It records the span for each one.
- `run_turn` returns only the assistant text added during this turn (`before` and the message count), not the whole
  history.
- The model call is not streamed. `complete` returns the whole answer, which is why the prompt asks for short answers.

**Tests**

- `backend/tests/test_graph.py::test_a_call_verifies_then_reads_a_bill_and_counts_its_model_use`
- `backend/tests/test_graph.py::test_a_model_that_keeps_calling_tools_is_stopped_and_the_call_handed_over`
- `backend/tests/test_graph.py::test_hand_off_ends_the_agent_and_marks_the_call`

## Stop 8. Tools and identity

**Read**

- `backend/app/agent/tools.py`: `run_tool`, the `TOOLS` registry at the end, `_customer` (raises until verified),
  `verify_identity`, `request_credit`, `hand_off`, and the spoken-form readers `spoken_code`, `spoken_date`,
  `_postcode`, `_spoken_day`, `_spoken_year`.
- `backend/app/agent/prompts.py`: `SYSTEM`, in particular the identity paragraph.

**Notice**

- `run_tool` validates arguments against the tool's model. A bad argument comes back to the model as an error it can
  act on; a `ToolError` does too. Nothing is raised to the caller.
- `verify_identity` takes the call's row lock, so three failed attempts cannot race. The failure message never says
  which detail was wrong. A verified call cannot be verified again for another customer.
- `spoken_code` reads "L T one zero zero" as `LT100`; `spoken_date` reads "the fourteenth of March nineteen eighty
  five". The model is told to pass what the caller said, word for word, because the server reads spoken digits.
- `request_credit` sums the call's applied credits and compares the total with the limit. The limit is per call, so
  several small credits cannot add past it without a supervisor.

**Tests**

- `backend/tests/test_tools.py::test_codes_are_read_the_way_people_say_them`
- `backend/tests/test_tools.py::test_dates_are_read_the_way_people_say_them`
- `backend/tests/test_tools.py::test_account_data_needs_a_verified_caller_and_then_is_that_callers`
- `backend/tests/test_tools.py::test_three_wrong_attempts_lock_verification_and_give_no_hint`
- `backend/tests/test_tools.py::test_a_verified_call_cannot_switch_to_another_account`
- `backend/tests/test_tools.py::test_another_organisations_customer_cannot_be_verified`
- `backend/tests/test_tools.py::test_tickets_hand_off_and_bad_arguments`
- `backend/tests/test_tools.py::test_an_administrator_changes_the_credit_limit_and_the_agent_follows_it`
- `backend/tests/test_eval_grader.py::test_account_data_before_verification_fails_even_if_everything_else_passes`

## Stop 9. The approval interrupt and its resume

**Read**

- `backend/app/agent/graph.py`: `tools` (where a pending credit is noted), `approval` (the `interrupt` call and the
  three outcomes), and `resume`.
- `backend/app/calls/service.py`: `decision_reached`.
- `backend/app/api/credits.py`: `decide`.

**Notice**

- Above the limit, `request_credit` inserts a `pending` row and returns `needs_approval`. `tools` notes it, and
  `after_tools` routes to `approval`.
- `approval` has no side effects before `interrupt()`. The node runs again from its start when resumed, so anything
  before the interrupt must be safe to repeat.
- The customer is told the credit is pending, and the next turn gets the fixed "still waiting" reply while the graph is
  paused.
- `decide` locks the credit row, refuses a second decision, and refuses a decider who was on the call. A refusal needs
  a reason. A decision on a live call resumes the graph; the agent's next sentence is returned as `agent_said` and
  stored.
- `decide` passes the credit id, and `decision_reached` resumes only if the call waits on that credit. Several credits
  over the limit in one step wait one after another, and `approval` reads each credit's row first, so one decided
  early is not waited for again. If a decision is recorded but never reaches the call (a failure in between), the
  next customer turn finds it decided and resumes with it.

**Tests**

- `backend/tests/test_graph.py::test_a_credit_over_the_limit_pauses_for_a_supervisor_and_resumes_after_a_restart`: the
  checkpoint survives a fresh graph object, as it would after a restart.
- `backend/tests/test_calls_api.py::test_a_supervisor_approves_a_credit_and_the_waiting_agent_tells_the_customer`
- `backend/tests/test_calls_api.py::test_whoever_placed_the_call_does_not_decide_its_credit`
- `frontend/e2e/calls.spec.ts`: "a credit over the limit waits for a supervisor, who approves it while the caller is on
  the line"

## Stop 10. Hand-off and take-over

**Read**

- `backend/app/agent/tools.py`: `hand_off`.
- `backend/app/calls/service.py`: `take_over`, `person_reply`.
- `backend/app/api/calls.py`: `take_over`, `reply`.
- `backend/app/voice/session.py`: `_follow_people`, which speaks a person's replies to the customer on the socket.

**Notice**

- The agent hands off by calling `hand_off`, or when a budget runs out. Either way the call becomes `handed_off` and
  the agent stops answering customer turns.
- A person takes the call with `take_over`. The check is that no one else holds it. The call's status changes and an
  event is published; the person's replies go through `person_reply`, which requires the caller to hold the call.
- `_follow_people` is a background task per socket. It reads the call's Redis stream from the moment the socket opens,
  so a reply typed by a person is spoken on the customer's socket.

**Tests**

- `backend/tests/test_calls_api.py::test_a_person_takes_over_and_the_agent_stops_answering`
- `backend/tests/test_graph.py::test_hand_off_ends_the_agent_and_marks_the_call`
- `frontend/e2e/calls.spec.ts`: "a caller asks for a person; an agent takes the call over and replies"

## Stop 11. The end of a call and the grounded note

**Read**

- `backend/app/calls/service.py`: `end_call`.
- `backend/app/calls/summary.py`: `write_summary`, `ground`, `_numbers`.
- `backend/app/agent/prompts.py`: `SUMMARY`.

**Notice**

- `end_call` loads the turns and events under lock, writes the note outside the lock (it calls the model), then sets
  the call to `ended` and publishes `call_ended`.
- `ground` splits each of `reason`, `outcome` and `follow_up` into sentences and drops any sentence with a number that
  does not appear in the transcript or the events. Removed sentences are listed in `unsupported`, and the browser shows
  them.
- When the model's answer is unusable, the note is plain and marked `written_by: system`. Nothing is marked unsupported,
  because nothing was generated.

**Tests**

- `backend/tests/test_calls_api.py::test_a_typed_call_verifies_reads_a_bill_and_ends_with_a_note`: the note's
  unsupported figure, "999.99", is removed and listed.
- `backend/tests/test_calls_api.py::test_without_a_usable_model_the_note_is_plain_and_nothing_is_marked_unsupported`

## Stop 12. Organisations, across the whole path

**Read**

- `backend/app/api/calls.py`: `get_call`, `call_events`, and `end` (each loads the call under the caller's
  organisation first).
- `backend/app/calls/service.py`: `load`, which raises `404` for a call that is not visible.

**Notice**

- Every route loads the call before doing anything else, and the load runs under the caller's organisation. Another
  organisation's call is simply not found.
- The checkpoint tables are not under row-level security. They are reached only after the call has been loaded
  (`docs/SECURITY.md`, *Known limitations*).

**Tests**

- `backend/tests/test_calls_api.py::test_another_organisation_sees_nothing`
- `frontend/e2e/calls.spec.ts`: "another organisation cannot open a call, by URL or through the API"
- `frontend/e2e/roles.spec.ts`: signing in and seeing only what each role may use

## Stop 13. Policies and citations

**Read**

- `backend/app/knowledge/index.py`: `sections`, `index_document`.
- `backend/app/knowledge/search.py`: `expand`, the `EVERYDAY` table, `SEARCH`.
- `backend/app/speech/text.py`: `CITATION`, `speakable`, `sentences`.

**Notice**

- Passages are `## n. Heading` sections. The citation of a passage is `[slug §n]`. The spoken text removes citations
  but the stored text keeps them.
- Search ORs the question's words, weights body, heading and title, and returns nothing when no word matches. That
  last rule prevents an arbitrary answer.
- The `EVERYDAY` table adds a policy's own words to phrasings customers use ("money back", "didn't turn up"). It is
  deliberately small and was written before the held-out questions.

**Tests**

- `backend/tests/test_knowledge.py::test_a_question_finds_the_passage_that_answers_it`
- `backend/tests/test_knowledge.py::test_a_question_with_no_matching_words_returns_nothing_rather_than_noise`
- `backend/tests/test_speech.py::test_citations_are_kept_in_text_but_not_spoken_and_replies_split_into_sentences`
- `backend/tests/test_eval_gate.py::test_retrieval_holds_its_recall`

## Stop 14. Providers under the graph

**Read**

- `backend/app/llm/factory.py`: `get_client`, `load_config`, `environment_config`, `build_provider`.
- `backend/app/llm/base.py`: `call_with_retry`.
- `backend/app/llm/openai_compat.py`: `merge_stream`, `OpenAICompatProvider.complete`.
- `backend/app/llm/anthropic.py`: `to_wire`, `AnthropicProvider.complete`.

**Notice**

- The graph never sees a provider: `factory.get_client` returns an `LLMClient` whose `complete` adds retries, the
  fallback and the cost.
- A wrong key is a client error, so it is not retried and fails at once. A timeout or a `529` is retried with back-off.

**Tests**

- `backend/tests/test_llm_retry.py::test_fallback_model_is_used_after_the_primary_is_exhausted`
- `backend/tests/test_llm_retry.py::test_errors_that_cannot_succeed_are_not_retried`
- `backend/tests/test_llm_adapters.py::test_plain_and_streamed_responses_give_the_same_result`
- `backend/tests/test_llm_adapters.py::test_anthropic_request_and_response_mapping`
- `backend/tests/test_llm_adapters.py::test_cost_counts_cached_input_at_a_tenth`

## Stop 15. The evaluation harness

The evaluation runs the same code as the browser, from scripts, and grades the result in the database. It is in
`backend/eval/`. Results are in `docs/EVALUATION.md`; read the harness first.

**Read**

- `backend/eval/common.py`: `configure_model` (points every model call at the gateway for the run and overrides the
  organisation's settings), `demo_user`, `place_call`.
- `backend/eval/scenarios.py`: the scripted calls and their split. The development and held-out splits are separate.
- `backend/eval/run_eval.py`: `grade`, `record`, `restore`, `run_one`, `aggregate`. `ACCOUNT_TOOLS` lists the tools that
  read or change an account; a call in which any of them runs before verification fails whatever else it did.
- `backend/eval/attacks.py`: one function per planted attack (`case_spouse`, `case_fake_system`, `case_big_credit`,
  `case_split_credits`, `case_other_account`, `case_prompt_leak`, `case_loop`).
- `backend/eval/run_retrieval.py` and `backend/eval/run_wer.py`: retrieval recall, and word error rate on synthesised
  speech with and without noise (`noisy`, `wer`, `normalise`).

**Notice**

- Grading reads events and stored state, not the reply text alone. A reply that says the right thing while the tool
  never ran fails.
- `restore` deletes the credits and tickets that earlier evaluation calls created for a planted customer, so one run
  cannot leave a pending credit for the next. The seed gives planted customers none.
- The ledger records that the held-out results were measured and not used for further tuning.

**Tests**

- `backend/tests/test_eval_grader.py::test_a_call_that_did_everything_right_passes`
- `backend/tests/test_eval_grader.py::test_a_credit_must_have_the_right_amount_and_status`
- `backend/tests/test_eval_gate.py::test_a_held_out_result_has_been_recorded_for_two_models`
- `backend/tests/test_eval_gate.py::test_every_recorded_attack_held_or_is_a_listed_limitation`
- `backend/tests/test_eval_api.py::test_recorded_results_of_each_kind_are_listed_in_summary`

Run an evaluation with `make eval-agent SPLIT=dev MODEL=<route>`, `make eval-attacks MODEL=<route>`,
`make eval-retrieval` (no model) or `make eval-wer`. They run in the test image and read `../.env.local` for the
gateway.

---

## Where to go next

- `docs/SECURITY.md` for which control protects what, and the tests that prove each one.
- `docs/DATABASE.md` for the tables behind each stop.
- `docs/API.md` for the wire format of the socket and the streams.
- `docs/PROVIDERS.md` to run the stop-14 code against a real model.
