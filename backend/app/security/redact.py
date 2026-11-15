"""Remove secrets from anything that is about to be stored, logged, traced or sent to a browser."""

import re
from typing import Any

# A key is sensitive when its name ENDS in one of these words (api_key, access_token, client_secret, password).
# Counts such as input_tokens or max_tokens are not secrets: masking them hid token usage from the agent.
SENSITIVE_KEY = re.compile(
    r"(?:^|[_\-.])(?:api[_\-]?key|key|token|secret|password|passwd|authorization|cookie|credentials?)$", re.IGNORECASE
)
SECRET_VALUE = re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_-]{16,}|\bBearer\s+[A-Za-z0-9._~+/=-]{16,}")
MASK = "[redacted]"


def redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {
            k: MASK if isinstance(k, str) and SENSITIVE_KEY.search(k.lower()) and v not in (None, "") else redact(v)
            for k, v in obj.items()
        }
    if isinstance(obj, list | tuple):
        return [redact(v) for v in obj]
    if isinstance(obj, str):
        return SECRET_VALUE.sub(MASK, obj)
    return obj
