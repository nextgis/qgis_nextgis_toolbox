import os

import pytest

from tests.manual.desktop import DesktopSession
from tests.manual.local_api import LocalToolbox


def pytest_addoption(parser):
    group = parser.getgroup("toolbox desktop")
    group.addoption(
        "--run-toolbox-desktop",
        action="store_true",
        help="Launch an isolated QGIS GUI",
    )
    group.addoption(
        "--toolbox-endpoint",
        help="Live catalog endpoint; defaults to a local fake API",
    )
    group.addoption(
        "--toolbox-run-demos",
        action="store_true",
        help="Submit every available demo (remote mutations!)",
    )
    group.addoption(
        "--toolbox-qgis-command",
        default="qgis",
        help="QGIS launcher, e.g. 'flatpak run com.nextgis.ngqgis'",
    )
    group.addoption(
        "--toolbox-tool",
        action="append",
        default=[],
        help="Restrict live runs to this tool (repeatable)",
    )
    group.addoption(
        "--toolbox-demo-timeout",
        type=int,
        default=300,
        help="Deadline in seconds for each demo",
    )


@pytest.fixture(scope="session")
def desktop(request):
    if not request.config.getoption("--run-toolbox-desktop"):
        pytest.skip("Explicit --run-toolbox-desktop is required")
    endpoint = request.config.getoption("--toolbox-endpoint")
    demos = request.config.getoption("--toolbox-run-demos")
    if endpoint and demos:
        if not os.environ.get("TOOLBOX_TEST_TOKEN"):
            pytest.fail(
                "Live demos require TOOLBOX_TEST_TOKEN; credentials are never copied from QGIS"
            )
        if not os.environ.get("TOOLBOX_TEST_ALLOW_REMOTE_DEMOS") == endpoint:
            pytest.fail(
                "Set TOOLBOX_TEST_ALLOW_REMOTE_DEMOS to the exact endpoint to authorize remote demos"
            )
    command = request.config.getoption("--toolbox-qgis-command")
    if request.config.getoption("--toolbox-demo-timeout") <= 0:
        pytest.fail("--toolbox-demo-timeout must be positive")
    with LocalToolbox() as server:
        with DesktopSession(
            endpoint or server.endpoint,
            command=command,
            token=os.environ.get("TOOLBOX_TEST_TOKEN", "") if endpoint else "",
        ) as session:
            print("\nDesktop artifacts: " + str(session.root))
            session.local_requests = server.requests if not endpoint else None
            session.local_submissions = (
                server.submissions if not endpoint else []
            )
            yield session
