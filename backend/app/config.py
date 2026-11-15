"""All configuration comes from environment variables; see .env.example."""

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LLM_PROVIDERS = ("openai_compat", "anthropic", "ollama", "stub")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://voiceops_app:voiceops_app@localhost:55462/voiceops"
    database_url_owner: str = "postgresql+psycopg://voiceops_owner:voiceops_owner@localhost:55462/voiceops"
    redis_url: str = "redis://localhost:56409/0"
    db_pool_size: int = 10

    secret_key: str = ""
    cors_origins: str = "http://localhost:3400"
    cookie_secure: bool = False
    session_hours: int = 12
    seed_demo: bool = True
    demo_customers: int = 200  # per demo organisation, loaded at first start
    allow_signup: bool = True
    trusted_proxy: bool = False  # read the client address from X-Forwarded-For (set when behind nginx)
    scrypt_n: int = 2**15
    login_attempts_per_minute: int = 5  # per e-mail address
    login_ip_per_minute: int = 30
    signup_ip_per_hour: int = 10

    llm_provider: str = "stub"
    llm_model: str = ""
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_fallback_model: str = ""
    llm_price_input_per_mtok: float = 3.0  # USD per million tokens; set to your provider's real prices
    llm_price_output_per_mtok: float = 15.0
    llm_max_concurrency: int = 16  # model calls in flight per process
    llm_max_output_tokens: int = 4096
    allow_private_llm_urls: bool = True  # false on a shared deployment: refuse base URLs on private networks

    call_max_model_calls: int = 80  # per call, all turns together
    turn_max_steps: int = 6  # model calls within one customer turn (tool use loops)
    call_max_tokens: int = 200_000
    call_max_cost_usd: float = 0.50
    org_daily_cost_usd: float = 20.00
    global_daily_cost_usd: float = 200.00  # all organisations together: bounds what open sign-up can spend
    org_max_live_calls: int = 20
    calls_per_minute: int = 10  # new calls per person
    customer_credit_30d: float = 25.00  # credit the agent may apply to one customer in 30 days without a supervisor
    verify_account_max_failures: int = 5  # failed checks on one account (any call) in 24 hours before it is locked
    verify_user_max_failures: int = 15  # failed checks on calls placed by one person in an hour
    call_max_turns: int = 200
    call_idle_minutes: int = 30  # a live call with no activity for this long is ended when the next call starts
    call_max_minutes: int = 20  # a call's time budget; once spent, the agent hands over politely
    credit_limit: float = 10.00  # default per-credit limit an agent may apply without a supervisor
    stub_responder: str = "app.agent.stub:demo_responder"  # behaviour of LLM_PROVIDER=stub

    # Speech. "local" runs the models in this process; "openai_compat" calls /audio/transcriptions and /audio/speech.
    stt_provider: str = "local"
    stt_model: str = "base.en"  # faster-whisper size, or the hosted model name
    stt_device: str = "cpu"  # cpu | cuda
    stt_compute_type: str = "int8"  # int8 on CPU; float16 or int8_float16 on the GPU
    stt_base_url: str = ""
    stt_api_key: str = ""
    tts_provider: str = "local"
    tts_voice: str = "en_US-lessac-medium"  # a Piper voice, or the hosted voice name
    tts_model: str = ""  # hosted only, e.g. tts-1
    tts_base_url: str = ""
    tts_api_key: str = ""
    models_dir: str = "/models"  # Piper voices and Whisper models, downloaded at image build
    vad_silence_ms: int = 600  # silence that ends a customer's turn
    vad_min_speech_ms: int = 250  # shorter sounds are not a turn (a cough, a click)
    max_turn_seconds: int = 30  # a longer monologue is cut and transcribed

    otel_exporter_otlp_endpoint: str = ""
    metrics_token: str = ""  # when set, /metrics requires "Authorization: Bearer <token>"
    log_level: str = "INFO"

    @field_validator("llm_provider")
    @classmethod
    def _known_provider(cls, value: str) -> str:
        if value not in LLM_PROVIDERS:  # a typo must not quietly become the stub
            raise ValueError(f"LLM_PROVIDER must be one of {', '.join(LLM_PROVIDERS)}; got {value!r}")
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
