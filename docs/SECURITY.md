# Security

What is defended, how, and what is not. Each control names the test that exercises it.

## What is different about a voice line

On a phone line the attacker is the caller. Anything said reaches the model, and callers try what they would try on
a human agent: claim to be the account holder's spouse, say a supervisor already agreed, ask for "just the
balance", read an account number they found on a letter. So the controls that matter are the ones the server
enforces whatever the model is talked into.

## Position on prompt injection

Prompt injection is treated as unsolved. The instructions tell the model that what the caller says is a customer's
request, never an instruction that changes the rules, and in the attack suite Claude Sonnet 5.5 did not follow the
planted instructions (`EVALUATION.md`). Nothing depends on that. The design question is: *if the model were fully
controlled by the caller, what could it do?*

| It could | It could not |
|---|---|
| Answer from the organisation's policies, and say something wrong or rude | Read any account data before the server verified the caller on this call: the account tools take no customer id; they act on the call's verified customer or refuse |
| Try verification with guessed details | Try more than three times on a call (then verification is locked for that call); learn which detail was wrong |
| Read the verified caller's own bills, services, outages and credits | Switch the call to another account once verified, or read another organisation's anything (row-level security) |
| Open tickets for the verified caller | Close tickets, change contact details or services (no such tool) |
| Apply credits up to the organisation's limit per call (10.00 by default) | Apply more on one call, in one credit or several: the rest waits for a supervisor who was not on the call |
| Hand the call to a person | Take a person's place: people's replies are typed by signed-in staff |
| Spend the call's budget | Exceed the per-turn and per-call limits on model calls, tokens and cost, or the organisation's daily limit |

## Controls

| Control | How | Proven by |
|---|---|---|
| Identity before account data | `verify_identity` matches account number or phone, postcode and date of birth on the server (spoken forms normalised); the call row records the verified customer; every account tool reads it | `tests/test_tools.py::test_account_data_needs_a_verified_caller_and_then_is_that_callers`; evaluation check "no account data before verification" on every call |
| Lockout | Three failed checks lock verification for the call, with no hint which detail was wrong; the failure count is updated under a row lock. Across calls: five failed checks on one account in 24 hours, or fifteen on calls placed by one person in an hour, refuse further checks (counted in Redis under a hash, not the account number) | `tests/test_tools.py::test_three_wrong_attempts_lock_verification_and_give_no_hint`, `::test_failed_checks_on_one_account_add_up_across_calls_and_then_lock_it` |
| One account per call | A verified call cannot be re-verified as someone else | `tests/test_tools.py::test_a_verified_call_cannot_switch_to_another_account` |
| Credit limits | The sum the agent applies on one call stays within the limit (10.00), and what it applies to one customer in 30 days without a supervisor stays within 25.00 (`CUSTOMER_CREDIT_30D`); the rest is pending | `tests/test_tools.py::test_credits_up_to_the_limit_per_call_apply_and_beyond_wait_for_a_supervisor`, `::test_credits_without_a_supervisor_are_capped_per_customer_over_thirty_days` |
| Separation of duties | A credit is decided by a supervisor who neither placed nor handled the call; a refusal needs a reason | `tests/test_calls_api.py::test_whoever_placed_the_call_does_not_decide_its_credit` |
| Verification details masked | Until a caller is verified, the account number, postcode and date of birth they say are stored and streamed as `[masked]`. The agent is given the words as said; the verification event holds only the result | `tests/test_calls_api.py::test_the_details_a_caller_gives_to_verify_are_masked_in_the_transcript_but_not_for_the_agent`, `::test_masking_leaves_ordinary_talk_alone` |
| Shared phone numbers | A phone number that several accounts share cannot verify anyone; the caller is asked for the account number, and the attempt is neither a success nor a failed check | `tests/test_tools.py::test_a_phone_number_shared_by_two_accounts_is_not_a_way_in` |
| System-note marker | The `[Note from the system, not from the customer]` marker is removed from what a caller says, so a caller cannot pass words off as an agent note | `tests/test_calls_api.py::test_a_caller_cannot_speak_the_system_note_prefix` |
| Grounded CRM note amounts | A money amount in the note must appear in an agent turn or an event; a figure the caller said alone is removed | `tests/test_calls_api.py::test_the_note_grounds_amounts_only_in_what_the_agent_and_the_events_say` |
| Call time budget | A call has `CALL_MAX_MINUTES` (20); when it is spent the agent says so and passes the call to a person, without calling the model | `tests/test_calls_api.py::test_a_call_past_its_time_limit_is_passed_to_a_person_politely` |
| Human take-over | Only one person handles a call; only they reply; the agent stops answering, its audio stops at once, a reply it was preparing is not given, and the tools that change the account refuse once a person has the call; the person gets a brief built from the call's events | `tests/test_tools.py::test_tools_that_change_the_account_refuse_once_a_person_has_the_call`; `tests/test_calls_api.py::test_a_take_over_during_the_agents_turn_drops_its_reply_and_leaves_a_brief`; `tests/test_voice_session.py::test_a_take_over_while_the_agent_speaks_stops_its_audio`; `tests/test_calls_api.py::test_a_person_takes_over_and_the_agent_stops_answering` |
| Tenancy | Forced row-level security on every tenant table; the application role owns none | `tests/test_tenant_isolation.py`; `tests/test_calls_api.py::test_another_organisation_sees_nothing` |
| The voice socket | Signed in by the session cookie; the `Origin` header must be present and one of the deployment's origins (a WebSocket is not covered by CORS); only the person who placed the call may open its socket; frames over 64 KB are dropped; idle sockets close after 5 minutes (the page pings every minute, so a muted caller stays connected) | `app/api/voice.py`; `tests/test_security_basics.py::test_a_voice_socket_without_an_origin_header_is_refused` |
| Grounded notes | The CRM note drops any sentence with a figure found in no turn or event, and lists it | `tests/test_calls_api.py::test_a_typed_call_verifies_reads_a_bill_and_ends_with_a_note` |
| Spend limits | Before every model call: the call's model calls, tokens and cost, the organisation's spend today and all organisations' spend today; over any, the agent apologises and hands the call to a person without calling the model. The CRM note's model call is checked against the daily limits too, its cost is added to the call, and it reads at most 20,000 characters of transcript; a call has at most 200 turns | `tests/test_calls_api.py::test_an_organisation_over_its_daily_model_spend_is_passed_to_a_person_without_a_model_call`, `::test_all_organisations_over_the_global_daily_spend_stop_the_agent_too` |
| A model outage | A turn whose model call fails (after retries and the fallback model) hands the call to a person with an apology, never a dropped call | `tests/test_calls_api.py::test_when_the_model_fails_the_caller_hears_an_apology_and_is_passed_to_a_person` |
| Credit decisions bound to their credit | A supervisor's decision resumes the call only if it is the credit the call is waiting on; several credits over the limit in one step each wait; a credit decided early is read from its row when the call reaches it | `tests/test_calls_api.py::test_two_credits_in_one_step_each_wait_and_a_decision_resumes_only_the_credit_it_decides` |
| Malformed and excess voice input | An odd-length audio frame and a text frame that is not a JSON object are dropped without ending the socket; audio faster than real time beyond two seconds is dropped | `tests/test_security_basics.py::test_a_frame_with_an_odd_number_of_bytes_is_dropped_not_fatal`, `tests/test_voice_session.py::test_audio_faster_than_real_time_is_capped_so_one_call_cannot_flood_the_detector` |
| Model configuration | An unknown `LLM_PROVIDER` is a start-up error, not the stub; a saved key that cannot be decrypted is reported on the settings screen and fails a model call with a message to an administrator | `tests/test_llm_settings.py::test_an_unknown_llm_provider_is_a_configuration_error_not_the_stub`, `::test_an_unreadable_saved_key_is_a_clear_error_not_a_crash` |
| Redis outage | Sessions are read from PostgreSQL when the cache is down; rate-limited routes answer 503 with `Retry-After` | `tests/test_security_basics.py::test_signed_in_requests_survive_a_redis_outage`, `::test_a_rate_limited_route_during_a_redis_outage_says_when_to_retry` |
| Overload | A request that cannot get a database connection gets 503 with `Retry-After`, not 500; an organisation has at most 20 live calls (calls idle for 30 minutes are ended first, and a closed socket ends its call); each person may start 10 calls a minute (keyed by person, not address) | `tests/test_health.py::test_an_exhausted_connection_pool_is_a_503_to_retry_not_a_500` |

## OWASP Top 10 for LLM Applications (2025), briefly

| Risk | Where it is handled |
|---|---|
| LLM01 Prompt injection | Server-side identity, scoping and limits above; `eval/attacks.py` (spouse, fake_system, big_credit, split_credits, other_account) |
| LLM02 Sensitive information disclosure | No tool returns another customer; dates of birth, full postcodes and phone numbers are never read back (prompt) and the verification event stores no personal details |
| LLM05 Improper output handling | Tool arguments validated by schema; replies rendered by React as text; citations are stripped before speech |
| LLM06 Excessive agency | Eight tools; the only writes are tickets, credits within the limit, and hand-off |
| LLM07 System prompt leakage | The prompt holds no secret; `eval/attacks.py` (prompt_leak) |
| LLM10 Unbounded consumption | Per-turn steps, per-call model calls, tokens and cost, daily limits; `eval/attacks.py` (loop); live-call cap |

## Known limitations

- **Viewers read transcripts.** The viewer role sees calls, their transcripts and notes (it is the read-only role
  for team leads and quality reviewers); it cannot take over, reply or decide credits. An organisation that must
  restrict transcripts to supervisors would add a role check to `GET /api/calls/{id}`.
- **Anyone signed in can place a call**, as the demo's customer line. A public deployment needs its own entry point
  (a per-organisation widget token, rate limits per address) in front of `POST /api/calls`.
- **Verification details are masked only in the transcript and the live stream.** The agent's checkpoint keeps them as
  said (the agent needs them in its context); no API returns the checkpoint. A caller who gives details after being
  verified is not masked.
- **Knowledge-based verification is weak** in the real world: postcodes and dates of birth leak. A production line
  would add a one-time code to the phone or e-mail on the account; the policy text already mentions it.
- **Recordings are not kept.** Only transcripts are stored; if audio were kept, a consent prompt would be needed.
- **LangGraph's checkpoint tables are not row-level-secured**: they are keyed by thread id (the call id, a random
  UUID) and the server reads a checkpoint only after loading its call under the caller's organisation.
- **No voice biometrics or liveness**: a recording of the real customer's details passes the same checks.
- **Spoken-form normalisation** can mishear: "oh" is read as zero in codes; a postcode said with homophones may fail
  and count as an attempt.
