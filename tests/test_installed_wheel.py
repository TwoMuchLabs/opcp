"""Guard for the release workflow: the wheel test run must exercise the installed wheel.

Skipped in normal development. The release workflow sets OPCP_EXPECT_INSTALLED=1 after installing
the wheel, so a change to how tests are run that silently imports the source tree instead (for
example `python -m pytest`, which puts the current directory on sys.path) fails the release
rather than shipping an untested wheel. Ported from #24.
"""

import os
from pathlib import Path

import pytest

import opcp


@pytest.mark.skipif(os.environ.get("OPCP_EXPECT_INSTALLED") != "1", reason="only in the release workflow")
def test_tests_import_the_installed_package_not_the_checkout():
    checkout = Path(__file__).resolve().parent.parent
    assert checkout not in Path(opcp.__file__).resolve().parents, opcp.__file__
