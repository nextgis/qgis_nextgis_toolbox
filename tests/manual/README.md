# Manual QGIS desktop integration

This suite is **not discovered by ordinary `pytest`**: its entry point is
`desktop_suite.py`, not `test_*.py`. Even explicit collection requires
`--run-toolbox-desktop` before it can launch QGIS. Do not add it to unattended CI.

## Local, deterministic run

From the repository root, with Python, pytest and QGIS installed:

```sh
python3 -m pytest -q -s tests/manual/desktop_suite.py --run-toolbox-desktop
```

For headless Linux, prefix the command with `QT_QPA_PLATFORM=offscreen` or use
`xvfb-run -a`. A separate **real QGIS desktop process** runs with a fresh profile,
auth database, copied Toolbox plugin and copied probe plugin. Your running QGIS,
installed plugins and project are not reloaded or edited by this suite.

The local HTTP service supplies two tools. The tests verify:

- successful plugin initialization, complete Processing provider registration;
- registered menu actions, settings factory, help action and catalog refresh;
- opening every catalog tool through `processing.createAlgorithmDialog`,
  visible parameter panels, help and asynchronous demo-button patching;
- first demo preset execution for every demo tool through `processing.run`;
- demo file download, upload, task submission/polling, scalar result and ZIP
  download using artifact semantics, including inspection of archive contents.

The fake service validates the integration path, not the actual server's tool
implementation. Remote tool behavior needs the live mode below.

## Staging catalog and demo runs

Open every tool page without submitting tasks:

```sh
python3 -m pytest -q -s tests/manual/desktop_suite.py \
  --run-toolbox-desktop --toolbox-endpoint "$STAGING_ENDPOINT"
```

To submit **one job per tool with a demo preset**, provide a staging token via
the environment (never through arguments or a committed file), and explicitly
authorize the exact endpoint:

```sh
export TOOLBOX_TEST_TOKEN="$STAGING_TOKEN"
export TOOLBOX_TEST_ALLOW_REMOTE_DEMOS="$STAGING_ENDPOINT"
python3 -m pytest -q -s tests/manual/desktop_suite.py \
  --run-toolbox-desktop --toolbox-endpoint "$STAGING_ENDPOINT" \
  --toolbox-run-demos --toolbox-demo-timeout 300
```

The token is not copied from an existing QGIS profile or printed by the harness.
Local mode ignores ambient authentication. Live mode may incur costs and mutate
NGW resources referenced by demos; use a disposable staging account/resources.
`can_run=False`, missing required inputs and missing required outputs are
reported as failures, not silently skipped. Only the first preset is used,
matching Toolbox's demo button. Email and adding results to the project are off.
Use repeatable `--toolbox-tool hello` filters for focused debugging.

Every demo has a cancellation deadline, plus an outer controller watchdog.
A watchdog timeout poisons the session and stops further submissions. Killing
the local process **does not cancel a job already submitted to the server**;
inspect server task history before retrying. No automatic remote retries or
remote cleanup are performed.

## Script control

```python
from tests.manual.desktop import DesktopSession
from tests.manual.local_api import LocalToolbox

with LocalToolbox() as server:
    with DesktopSession(server.endpoint) as qgis:
        print(qgis.evaluate("api.state()"))
        qgis.evaluate("api.open_dialog('geocodetable')")
        state = qgis.wait(
            "api.dialog_state()", lambda value: value["demo_button"]
        )
        qgis.execute("iface.mapCanvas().refresh(); result = api.catalog()")
        qgis.evaluate("api.close_dialog()")
        print(qgis.evaluate("api.run_demo('geocodetable')"))
```

`execute` runs trusted Python on the GUI thread with persistent `api` and `iface`
variables. Assign a JSON-compatible value to `result` to return it.
`evaluate` is an expression shortcut; `wait` waits on observed runtime state.
The bridge is a private file mailbox, **not a network code-execution service**.
Only one command can run in a session at a time. Never feed it untrusted scripts
or inject credentials into script text.

`DesktopTools` in `probe_plugin/runtime.py` can also be imported through an
existing QGIS MCP session for debugging. It owns and closes only its own dialog.
Opening dialogs there verifies that installed build, not the isolated copy of
the current worktree. `run_demo` requires endpoint authorization even over MCP.

## Diagnostics and launchers

Each run retains its unique directory under `/tmp/opencode` by default (override
with `TOOLBOX_TEST_ARTIFACTS`). It contains `command.json`, `qgis.log`, optional
QGIS message logs, per-tool `dialogs.json` and `demos.json`, downloaded inputs,
results and the isolated profile. Reports are written after every tool, so a
crash does not erase preceding results. Treat staging artifacts as private data.
Remove only your own run directories when they are no longer needed.

Use `--toolbox-qgis-command '/path/to/qgis'` for another native QGIS version.
A sandbox launcher can also be supplied, e.g. `flatpak run ...`; ensure it can
access the artifact directory and receives the harness environment. The native
Linux launcher is the default and the verified path.

The regular suite is independent:

```sh
QT_QPA_PLATFORM=offscreen python3 -m pytest -q tests
```
