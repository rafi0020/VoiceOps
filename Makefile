.PHONY: dev-up dev-down check test test-live test-speech test-speech-live lint eval-agent eval-attacks eval-retrieval eval-wer
dev-up:    ## database, pooler and redis for local development and tests
	docker compose up -d --build db pgbouncer redis
dev-down:
	docker compose down
lint:
	cd backend && uv run ruff format --check -q . && uv run ruff check .
test:      ## everything except tests that call a real model
	cd backend && RUN_LIVE=0 uv run pytest -q
test-live: ## tests that call a real model through the gateway in ../.env.local
	cd backend && uv run pytest -q -m live
check: lint test
test-speech:  ## speech tests, in the test image (it has the models)
	docker compose --profile test run --rm --build tests
test-speech-live:  ## speech + real model, in the test image; reads NINEROUTER_API_KEY from ../.env.local without printing it
	@set -a && . ../.env.local && set +a && docker compose --profile test run --rm --build -e NINEROUTER_API_KEY \
		-e NINEROUTER_BASE_URL=http://host.docker.internal:20128/v1 tests python -m pytest -q -m "live and speech"

# Evaluation, in the test image (it has the speech models), against the development database (the demo data).
# MODEL is a route on the gateway named in ../.env.local (NINEROUTER_*), or set EVAL_BASE_URL / EVAL_API_KEY.
EVAL_RUN = @set -a && . ../.env.local && set +a && docker compose --profile test run --rm --build --user "$$(id -u):$$(id -g)" \
	-v "$$PWD/backend/eval:/srv/eval" -e NINEROUTER_API_KEY -e NINEROUTER_BASE_URL=http://host.docker.internal:20128/v1 \
	-e DATABASE_URL=postgresql+psycopg://voiceops_app:$${VOICEOPS_APP_PASSWORD:-voiceops_app}@pgbouncer:6432/voiceops \
	-e DATABASE_URL_OWNER=postgresql+psycopg://voiceops_owner:$${VOICEOPS_OWNER_PASSWORD:-voiceops_owner}@db:5432/voiceops
eval-agent:      ## SPLIT=dev|test MODEL=...
	$(EVAL_RUN) tests python -m eval.run_eval --split $(SPLIT) --model $(MODEL)
eval-attacks:    ## MODEL=...
	$(EVAL_RUN) tests python -m eval.attacks --model $(MODEL)
eval-retrieval:  ## policy search recall on held-out questions (no model)
	$(EVAL_RUN) tests python -m eval.run_retrieval
eval-wer:        ## word error rate of the recogniser in STT_* (CPU base.en by default)
	$(EVAL_RUN) tests python -m eval.run_wer

