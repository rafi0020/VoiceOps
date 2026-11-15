"""Start-up waits for the database instead of giving up on the first refused connection.

Found while restarting the stack after the final review: the database container restarted under a running
PgBouncer, which cached the failed logins for a few seconds; the migrate job failed on its first query and the
API, workers and ingest never started."""

import pytest
from sqlalchemy.exc import OperationalError

from app.bootstrap import with_retries


def test_a_step_that_fails_to_connect_a_few_times_is_retried():
    calls = []

    def step():
        calls.append(1)
        if len(calls) < 3:
            raise OperationalError("select 1", {}, Exception("server login has been failing"))
        return "done"

    assert with_retries(step, attempts=5, delay_s=0) == "done" and len(calls) == 3


def test_it_gives_up_after_the_last_attempt_and_other_errors_are_not_retried():
    def down():
        raise OperationalError("select 1", {}, Exception("refused"))

    with pytest.raises(OperationalError):
        with_retries(down, attempts=3, delay_s=0)
    calls = []

    def broken():
        calls.append(1)
        raise ValueError("a bug, not the network")

    with pytest.raises(ValueError):
        with_retries(broken, attempts=3, delay_s=0)
    assert len(calls) == 1
