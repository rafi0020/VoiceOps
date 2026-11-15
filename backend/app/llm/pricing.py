"""Cost estimation.

Prices differ by provider and change over time, so they are configuration, not code: each organisation's
model settings carry a price per million input and output tokens, with defaults from the environment.
Cost figures in this application are therefore estimates based on those settings. Cached input tokens are
charged at `CACHED_INPUT_FACTOR` of the input price, which matches how the major providers bill cache reads.
"""

from decimal import Decimal

from app.llm.types import Usage

CACHED_INPUT_FACTOR = Decimal("0.1")
MILLION = Decimal(1_000_000)


def cost_usd(usage: Usage, price_in_per_mtok: float, price_out_per_mtok: float) -> Decimal:
    fresh = max(0, usage.input_tokens - usage.cached_tokens)
    price_in, price_out = Decimal(str(price_in_per_mtok)), Decimal(str(price_out_per_mtok))
    total = (
        fresh * price_in + usage.cached_tokens * price_in * CACHED_INPUT_FACTOR + usage.output_tokens * price_out
    ) / MILLION
    return total.quantize(Decimal("0.000001"))
