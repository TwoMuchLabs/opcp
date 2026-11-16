"""The conformance runner must catch a runtime without its own idempotency (red-team R2-04)."""

from opcp.conformance import check_runtime
from opcp.runtime import ControlPlane

def test_runtime_conformance_catches_a_runtime_with_no_idempotency():
    # Red-team round 2: the runner's probe suppliers deduplicated by themselves, so a runtime that
    # never stored a response still passed "repeated idempotency key does not repeat the effect".
    class Forgets(dict):
        def __setitem__(self, key, value):
            pass

    class NoIdempotency(ControlPlane):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._responses = Forgets()

    report = check_runtime(NoIdempotency)
    failed = {name for name, ok, _ in report.checks if not ok}
    assert "repeated idempotency key does not repeat the effect" in failed
    assert check_runtime().passed
