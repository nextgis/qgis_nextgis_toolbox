import json
from pathlib import Path
from zipfile import ZipFile

import pytest


def test_startup_and_ui(desktop):
    state = desktop.evaluate("api.state()")
    assert state["state"] == "loaded"
    assert state["provider"] and state["menu"]
    assert state["tools"] > 0
    assert state["algorithms"] == state["tools"]
    assert desktop.root in Path(state["source_path"]).parents
    assert desktop.evaluate("api.ui()") == {
        "actions": 5,
        "settings": True,
        "help": True,
    }
    assert desktop.evaluate("iface.mainWindow().isVisible()")


def selected_tools(desktop, request):
    tools = desktop.evaluate("api.catalog()")
    selected = set(request.config.getoption("--toolbox-tool"))
    assert not selected.difference(tool["name"] for tool in tools), (
        "Unknown tool filter"
    )
    return [tool for tool in tools if not selected or tool["name"] in selected]


def test_refresh_catalog(desktop):
    names_before = desktop.evaluate("api.catalog()")
    assert desktop.evaluate("api.refresh()") == "loading"
    desktop.wait("api.state()", lambda state: state["state"] == "loaded")
    assert desktop.evaluate("api.catalog()") == names_before
    desktop.evaluate("api.ui()")


def test_all_processing_dialogs(desktop, request):
    report = []
    for tool in selected_tools(desktop, request):
        entry = {"tool": tool["name"]}
        try:
            desktop.evaluate("api.open_dialog(" + repr(tool["name"]) + ")")
            state = desktop.wait(
                "api.dialog_state()",
                lambda value: value["demo_button"] == value["expected_demo"],
                timeout=15,
            )
            assert state["visible"] and state["main_widget"]
            assert state["algorithm"] == tool["name"]
            assert state["help"]
            entry["status"] = "passed"
        except Exception as error:
            entry.update(status="failed", error=str(error))
        finally:
            if not desktop.broken:
                desktop.evaluate("api.close_dialog()")
        report.append(entry)
        (desktop.root / "dialogs.json").write_text(
            json.dumps(report, indent=2), "utf-8"
        )
        if desktop.broken:
            break
    failures = [entry for entry in report if entry["status"] == "failed"]
    assert not failures, failures


def test_all_demo_tools(desktop, request):
    live = request.config.getoption("--toolbox-endpoint")
    if live and not request.config.getoption("--toolbox-run-demos"):
        pytest.skip("Live task submission requires --toolbox-run-demos")
    tools = [tool for tool in selected_tools(desktop, request) if tool["demo"]]
    assert tools, "No demo tools found"
    timeout = request.config.getoption("--toolbox-demo-timeout")
    report = []
    for tool in tools:
        entry = {"tool": tool["name"]}
        try:
            result = desktop.evaluate(
                f"api.run_demo({tool['name']!r}, timeout={timeout})",
                timeout=timeout + 60,
            )
            entry.update(status="passed", result=result)
        except Exception as error:
            entry.update(status="failed", error=str(error))
        report.append(entry)
        (desktop.root / "demos.json").write_text(
            json.dumps(report, indent=2), "utf-8"
        )
        if desktop.broken:
            break
    failures = [entry for entry in report if entry["status"] == "failed"]
    assert not failures, failures
    if not live and any(tool["name"] == "hello" for tool in tools):
        hello = next(entry for entry in report if entry["tool"] == "hello")
        assert hello["result"]["outputs"] == {"message": "hello"}
    if not live and any(tool["name"] == "geocodetable" for tool in tools):
        assert ("POST", "/api/upload") in desktop.local_requests
        assert ("GET", "/api/download/storage/demo") in desktop.local_requests
        assert (
            "GET",
            "/api/download/storage/result.file",
        ) in desktop.local_requests
        path = desktop.root / "outputs/geocodetable/result_file.zip"
        with ZipFile(path) as archive:
            assert "result.csv" in archive.namelist()
        submission = next(
            item
            for item in desktop.local_submissions
            if item["tool"] == "geocodetable"
        )
        assert submission["inputs"]["addr_field"] == "address"
        assert submission["inputs"]["table"]["local"]["uuid"] == "uploaded"
        assert submission["emailing"] is False
