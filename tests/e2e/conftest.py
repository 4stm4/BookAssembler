"""Every pipeline run of the end-to-end tests: no analyzer may fail unseen.

PipelineRunner rolls a failing analyzer back and runs on (RFC 0005 §6.1),
and the document comes out whole but without that analyzer's work. A test
of what is left can pass on it: the table analyzer failed on the scanned
spec page from 2 October to 23 October, every table of the page lost, and
nothing was red. Here a run that rolled an analyzer back fails, naming it
and its error - in the test, or in the module fixture that ran it.

Session-wide, so it is in place before a module's own fixtures run the
pipeline; it makes the tests stricter and changes none of them.
"""

import pytest

from src.analyzers.pipeline import PipelineRunner


@pytest.fixture(scope="session", autouse=True)
def no_analyzer_fails_unseen():
    execute = PipelineRunner.execute

    def checked(self, *args, **kwargs):
        result = execute(self, *args, **kwargs)
        if self.failures:
            raise AssertionError(
                "analyzer(s) failed and were rolled back: "
                + "; ".join(f"{name}: {error}" for name, error in self.failures)
            )
        return result

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(PipelineRunner, "execute", checked)
        yield
