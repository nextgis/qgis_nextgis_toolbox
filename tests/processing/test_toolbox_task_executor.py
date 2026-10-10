# NextGIS Toolbox
# Copyright (C) 2026  NextGIS
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or any
# later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, see <https://www.gnu.org/licenses/>.

import importlib
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List, Optional
from zipfile import ZipFile

import pytest
from qgis.core import Qgis
from qgis.PyQt.QtWidgets import QPushButton

from nextgis_toolbox.core.exceptions import (
    ToolboxFileUploadError,
    ToolboxTaskExecutionError,
    ToolboxTaskFailedError,
    ToolboxTaskTimeoutError,
)
from nextgis_toolbox.processing.task_polling_policy import (
    TaskExecutionSnapshot,
    TaskExecutionState,
    TaskPollingPolicy,
)
from nextgis_toolbox.processing.toolbox_task_executor import (
    ToolboxTaskExecutor,
)
from nextgis_toolbox.tasks.models import (
    TaskResult,
    TaskStatus,
    ToolboxTaskInformation,
)
from nextgis_toolbox.tools.models import (
    InputParameterType,
    OutputParameterType,
    ToolboxTool,
    ToolInputParameter,
    ToolOutputParameter,
)
from nextgis_toolbox.tools.semantics import ToolOutputSemantic


@pytest.fixture(autouse=True)
def _init_qgis(qgis_app) -> None:
    del qgis_app


class FakeClock:
    def __init__(self) -> None:
        self.current = 0.0
        self.sleep_calls: List[float] = []

    def monotonic(self) -> float:
        return self.current

    def sleep(self, seconds: float) -> None:
        self.sleep_calls.append(seconds)
        self.current += seconds


class FakeFeedback:
    def __init__(self, *, cancel_after_checks: Optional[int] = None) -> None:
        self.cancel_after_checks = cancel_after_checks
        self.cancel_checks = 0
        self.progress_texts: List[str] = []
        self.progress_values: List[int] = []
        self.infos: List[str] = []
        self.debug_infos: List[str] = []
        self.formatted_messages: List[List[str]] = []
        self._canceled = False

    def isCanceled(self) -> bool:
        self.cancel_checks += 1
        if (
            self.cancel_after_checks is not None
            and self.cancel_checks >= self.cancel_after_checks
        ):
            self._canceled = True
        return self._canceled

    def setProgressText(self, text: str) -> None:
        self.progress_texts.append(text)

    def pushDebugInfo(self, text: str) -> None:
        self.debug_infos.append(text)

    def setProgress(self, value: int) -> None:
        self.progress_values.append(value)

    def pushInfo(self, text: str) -> None:
        self.infos.append(text)

    def pushFormattedMessage(self, html: str, text: str) -> None:
        self.formatted_messages.append([html, text])


class FakeNotifier:
    def __init__(self) -> None:
        self.messages: List[Dict[str, Any]] = []

    def display_message(self, message: str, **kwargs: Any) -> str:
        self.messages.append({"message": message, **kwargs})
        return "message-id"


class FakePluginInterface:
    class Mode:
        GUI = "gui"

    def __init__(self, notifier: FakeNotifier) -> None:
        self.mode = self.Mode.GUI
        self.notifier = notifier


class FakeApiClient:
    def __init__(
        self,
        *,
        tasks: Optional[List[Any]] = None,
        upload_responses: Optional[List[Any]] = None,
        task_id: str = "task-1",
        endpoint: str = "https://sandbox.nextgis.test",
    ) -> None:
        self.tasks = [] if tasks is None else list(tasks)
        self.upload_responses = (
            [] if upload_responses is None else list(upload_responses)
        )
        self.task_id = task_id
        self.endpoint = endpoint
        self.submitted_inputs: List[Dict[str, Any]] = []
        self.submitted_emailing: List[bool] = []
        self.submitted_operations: List[str] = []
        self.downloaded_requests: List[Dict[str, Path]] = []
        self.uploaded_paths: List[Path] = []
        self.retrieved_task_ids: List[str] = []

    def submit_task(
        self,
        operation: str,
        inputs: Dict[str, Any],
        emailing: bool = False,
        feedback=None,
    ) -> str:
        del feedback
        self.submitted_operations.append(operation)
        self.submitted_emailing.append(emailing)
        self.submitted_inputs.append(inputs)
        return self.task_id

    def task_information(
        self,
        task_id: str,
        feedback=None,
    ) -> ToolboxTaskInformation:
        del feedback
        self.retrieved_task_ids.append(task_id)
        if not self.tasks:
            raise AssertionError("No fake task payloads left")

        task_or_error = self.tasks.pop(0)
        if isinstance(task_or_error, Exception):
            raise task_or_error

        return task_or_error

    def task_results_url(self, task_id: str) -> str:
        return f"{self.endpoint}/orders?selected={task_id}"

    def upload(self, path: Path, feedback=None) -> Dict[str, Any]:
        del feedback
        self.uploaded_paths.append(Path(path))
        if not self.upload_responses:
            raise AssertionError("No fake upload response left")

        response_or_error = self.upload_responses.pop(0)
        if isinstance(response_or_error, Exception):
            raise response_or_error

        return response_or_error

    def download(
        self,
        path: str,
        destination_path: Path,
        query_params=None,
        feedback=None,
    ) -> Path:
        del query_params, feedback

        target_path = Path(destination_path)
        if target_path.suffix:
            saved_path = target_path
        else:
            saved_path = target_path / Path(path).name

        saved_path.parent.mkdir(parents=True, exist_ok=True)
        saved_path.write_text(f"downloaded:{path}", encoding="utf-8")
        self.downloaded_requests.append(
            {
                "destination": Path(destination_path),
                "saved_path": saved_path,
            }
        )
        return saved_path


def make_parameter(
    name: str,
    parameter_type: str,
    *,
    required: bool = True,
) -> ToolInputParameter:
    return ToolInputParameter(
        name=name,
        parameter_type=InputParameterType.from_json(parameter_type),
        alias=name.replace("_", " ").title(),
        description=None,
        required=required,
        choices=None,
    )


def make_output_parameter(
    name: str,
    parameter_type: str,
    *,
    required: bool = True,
    alias: Optional[str] = None,
) -> ToolOutputParameter:
    return ToolOutputParameter(
        name=name,
        parameter_type=OutputParameterType.from_json(parameter_type),
        alias=alias or name.replace("_", " ").title(),
        description=None,
        required=required,
    )


def make_tool(
    *inputs: ToolInputParameter,
    outputs: Optional[List[ToolOutputParameter]] = None,
) -> ToolboxTool:
    return ToolboxTool(
        id=1,
        name="demo-tool",
        alias="Demo Tool",
        description="Description",
        is_dev=False,
        is_free=True,
        is_new=False,
        is_featured=False,
        can_run=True,
        tag_ids=[],
        inputs=list(inputs),
        outputs=[] if outputs is None else outputs,
        presets=[],
        help="<p>Docs</p>",
    )


def make_task(
    status: TaskStatus,
    *,
    progress: Optional[float] = 0.0,
    error: Optional[str] = None,
    results: Optional[List[TaskResult]] = None,
) -> ToolboxTaskInformation:
    return ToolboxTaskInformation(
        tool="demo-tool",
        status=status,
        progress=progress,
        error=error,
        results=[] if results is None else results,
        operation="demo-tool",
    )


def make_file_reference(name: str, uuid: str) -> Dict[str, Any]:
    return {
        "name": name,
        "local": {"uuid": uuid},
        "s3": None,
    }


def make_executor(
    *,
    tool: ToolboxTool,
    resolved_values: Dict[str, Any],
    client: FakeApiClient,
    clock: Optional[FakeClock] = None,
    notifier: Optional[FakeNotifier] = None,
    output_destination_resolver=None,
    wait_timeout_seconds: Optional[float] = None,
) -> ToolboxTaskExecutor:
    fake_clock = FakeClock() if clock is None else clock

    def resolve(
        parameter: ToolInputParameter,
        parameters: Dict[str, Any],
        context,
    ) -> Any:
        del parameters, context
        return resolved_values[parameter.name]

    return ToolboxTaskExecutor(
        api_client=client,
        task_submitter=client.submit_task,
        task_information_resolver=client.task_information,
        task_results_url_resolver=client.task_results_url,
        tool=tool,
        parameter_resolver=resolve,
        notifier=notifier,
        output_destination_resolver=output_destination_resolver,
        polling_policy=TaskPollingPolicy(jitter_enabled=False),
        monotonic_clock=fake_clock.monotonic,
        sleeper=fake_clock.sleep,
        wait_timeout_seconds=wait_timeout_seconds,
    )


@pytest.mark.parametrize(
    "result_name, value, extensions, expected",
    [
        ("result", "storage/result.file", ["zip"], "result.zip"),
        ("report.csv", "storage/result.file", ["zip"], "report.csv"),
        ("result", "storage/result.csv", ["zip", "csv"], "result.csv"),
        ("result", "storage/result.file", ["zip", "csv"], None),
    ],
)
def test_archive_result_filename_uses_artifact_semantics(
    result_name, value, extensions, expected
):
    output = ToolOutputParameter(
        name="result",
        parameter_type=OutputParameterType.FILE,
        alias=None,
        description=None,
        required=True,
        output_semantic=ToolOutputSemantic(
            kind="other",
            constraints={"extensions": extensions},
            archive_contents=[ToolOutputSemantic(kind="table")],
        ),
    )
    executor = make_executor(
        tool=make_tool(outputs=[output]),
        resolved_values={},
        client=FakeApiClient(tasks=[]),
    )
    assert (
        executor._preferred_result_filename(
            TaskResult(name=result_name, value=value), output
        )
        == expected
    )


def test_execute_downloads_archive_using_semantic_extension(tmp_path):
    output = replace(
        make_output_parameter("result", "file"),
        output_semantic=ToolOutputSemantic(
            kind="other",
            constraints={"extensions": ["zip"]},
            archive_contents=[ToolOutputSemantic(kind="table")],
        ),
    )
    client = FakeApiClient(
        tasks=[
            make_task(
                TaskStatus.SUCCESS,
                progress=1.0,
                results=[
                    TaskResult(name="result", value="storage/result.file")
                ],
            )
        ]
    )
    executor = make_executor(
        tool=make_tool(outputs=[output]),
        resolved_values={},
        client=client,
        output_destination_resolver=lambda *args: tmp_path / "result.file",
    )

    results = executor.execute({}, object(), FakeFeedback())

    assert results == {"result": str(tmp_path / "result.zip")}
    assert (
        client.downloaded_requests[0]["destination"] == tmp_path / "result.zip"
    )
    assert (tmp_path / "result.zip").is_file()


def test_execute_successful_task_updates_feedback_and_returns_empty_dict(
    tmp_path: Path,
) -> None:
    del tmp_path

    tool = make_tool(make_parameter("source", "string"))
    task_results = [
        TaskResult(
            name="result",
            value="storage/result-1",
        )
    ]
    client = FakeApiClient(
        tasks=[
            make_task(TaskStatus.NEW, progress=0.0),
            make_task(TaskStatus.ASSIGNED, progress=0.0),
            make_task(TaskStatus.STARTED, progress=0.4),
            make_task(
                TaskStatus.SUCCESS,
                progress=1.0,
                results=task_results,
            ),
        ]
    )
    clock = FakeClock()
    feedback = FakeFeedback()
    executor = make_executor(
        tool=tool,
        resolved_values={"source": "value"},
        client=client,
        clock=clock,
    )

    result = executor.execute({}, object(), feedback)

    assert result == {}
    assert client.submitted_inputs == [{"source": "value"}]
    assert clock.sleep_calls == [1.0, 2.0, 1.0]
    assert feedback.progress_values == [0, 40, 100]
    assert feedback.formatted_messages[0][1].endswith(
        "https://sandbox.nextgis.test/orders?selected=task-1"
    )


def test_execute_fast_successful_task_polls_immediately() -> None:
    tool = make_tool(make_parameter("source", "string"))
    client = FakeApiClient(tasks=[make_task(TaskStatus.SUCCESS, progress=1.0)])
    clock = FakeClock()
    feedback = FakeFeedback()
    executor = make_executor(
        tool=tool,
        resolved_values={"source": "value"},
        client=client,
        clock=clock,
    )

    result = executor.execute({}, object(), feedback)

    assert result == {}
    assert clock.sleep_calls == []
    assert feedback.progress_values == [100]


def test_running_polling_policy_grows_with_elapsed_time() -> None:
    policy = TaskPollingPolicy(jitter_enabled=False)
    expected = [1.0, 5.0, 15.0, 30.0, 60.0, 300.0]
    actual = []

    for elapsed_seconds in (0.0, 10.0, 60.0, 600.0, 1800.0, 3600.0):
        snapshot = TaskExecutionSnapshot(
            task_id="task-1",
            backend_status=TaskStatus.STARTED,
            execution_state=TaskExecutionState.RUNNING,
            progress=0.5,
            error=None,
            elapsed_seconds=elapsed_seconds,
        )
        actual.append(
            policy.next_interval(
                snapshot,
                state_elapsed_seconds=elapsed_seconds,
                state_poll_count=1,
            )
        )

    assert actual == expected


def test_pending_and_finishing_polling_policies_follow_schedule() -> None:
    policy = TaskPollingPolicy(jitter_enabled=False)
    pending_snapshot = TaskExecutionSnapshot(
        task_id="task-1",
        backend_status=TaskStatus.NEW,
        execution_state=TaskExecutionState.PENDING,
        progress=0.0,
        error=None,
        elapsed_seconds=0.0,
    )
    finishing_snapshot = TaskExecutionSnapshot(
        task_id="task-1",
        backend_status=TaskStatus.STARTED,
        execution_state=TaskExecutionState.FINISHING,
        progress=1.0,
        error=None,
        elapsed_seconds=60.0,
    )

    pending_intervals = [
        policy.next_interval(
            pending_snapshot,
            state_elapsed_seconds=0.0,
            state_poll_count=count,
        )
        for count in range(1, 7)
    ]
    finishing_intervals = [
        policy.next_interval(
            finishing_snapshot,
            state_elapsed_seconds=elapsed_seconds,
            state_poll_count=1,
        )
        for elapsed_seconds in (0.0, 30.0, 300.0)
    ]

    assert pending_intervals == [1.0, 2.0, 3.0, 5.0, 10.0, 10.0]
    assert finishing_intervals == [2.0, 10.0, 30.0]


def test_execute_marks_finishing_before_success() -> None:
    tool = make_tool(make_parameter("source", "string"))
    client = FakeApiClient(
        tasks=[
            make_task(TaskStatus.STARTED, progress=0.5),
            make_task(TaskStatus.STARTED, progress=1.0),
            make_task(TaskStatus.SUCCESS, progress=1.0),
        ]
    )
    feedback = FakeFeedback()
    clock = FakeClock()
    executor = make_executor(
        tool=tool,
        resolved_values={"source": "value"},
        client=client,
        clock=clock,
    )

    executor.execute({}, object(), feedback)

    assert "Task is being executed..." in feedback.progress_texts
    assert feedback.progress_texts.count("Finishing task...") == 1
    assert feedback.progress_values == [50, 100]
    assert clock.sleep_calls == [1.0, 2.0]


@pytest.mark.parametrize(
    "status",
    [
        TaskStatus.NEW,
        TaskStatus.ASSIGNED,
        TaskStatus.ACCEPTED,
        TaskStatus.STARTED,
        TaskStatus.UNKNOWN,
    ],
)
def test_map_execution_state_marks_full_progress_as_finishing_for_non_terminal_statuses(
    status: TaskStatus,
) -> None:
    tool = make_tool(make_parameter("source", "string"))
    executor = make_executor(
        tool=tool,
        resolved_values={"source": "value"},
        client=FakeApiClient(),
    )

    execution_state = executor._map_execution_state(
        make_task(status, progress=1.0),
        1.0,
        None,
    )

    assert execution_state == TaskExecutionState.FINISHING


def test_execute_passes_emailing_flag_to_submit_task() -> None:
    tool = make_tool(make_parameter("source", "string"))
    client = FakeApiClient(tasks=[make_task(TaskStatus.SUCCESS, progress=1.0)])
    executor = make_executor(
        tool=tool,
        resolved_values={"source": "value"},
        client=client,
    )

    executor.execute({}, object(), FakeFeedback(), emailing=True)

    assert client.submitted_emailing == [True]


def test_execute_downloads_declared_output_file_and_returns_path(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "result.zip"
    tool = make_tool(
        make_parameter("source", "string"),
        outputs=[make_output_parameter("result", "file")],
    )
    client = FakeApiClient(
        tasks=[
            make_task(
                TaskStatus.SUCCESS,
                progress=1.0,
                results=[
                    TaskResult(
                        name="result",
                        value="storage/result-1",
                    )
                ],
            )
        ]
    )
    executor = make_executor(
        tool=tool,
        resolved_values={"source": "value"},
        client=client,
        output_destination_resolver=lambda *_args, **_kwargs: output_path,
    )

    result = executor.execute({}, object(), FakeFeedback())

    assert result == {"result": str(output_path)}
    assert client.downloaded_requests == [
        {
            "destination": output_path,
            "saved_path": output_path,
        }
    ]


def test_execute_formats_local_output_as_file_link(tmp_path: Path) -> None:
    output_path = tmp_path / "result.zip"
    tool = make_tool(
        make_parameter("source", "string"),
        outputs=[make_output_parameter("result", "file")],
    )
    client = FakeApiClient(
        tasks=[
            make_task(
                TaskStatus.SUCCESS,
                progress=1.0,
                results=[
                    TaskResult(
                        name="result",
                        value="storage/result-1",
                    )
                ],
            )
        ]
    )
    feedback = FakeFeedback()
    executor = make_executor(
        tool=tool,
        resolved_values={"source": "value"},
        client=client,
        output_destination_resolver=lambda *_args, **_kwargs: output_path,
    )

    executor.execute({}, object(), feedback)

    assert output_path.as_uri() in feedback.formatted_messages[0][0]
    assert str(output_path) in feedback.formatted_messages[0][1]


def test_execute_adds_show_and_copy_actions_to_success_message(
    tmp_path: Path,
    monkeypatch,
) -> None:
    output_path = tmp_path / "result.zip"
    tool = make_tool(
        make_parameter("source", "string"),
        outputs=[make_output_parameter("result", "file")],
    )
    client = FakeApiClient(
        tasks=[
            make_task(
                TaskStatus.SUCCESS,
                progress=1.0,
                results=[
                    TaskResult(
                        name="result",
                        value="storage/result-1",
                    )
                ],
            )
        ]
    )
    notifier = FakeNotifier()
    plugin = FakePluginInterface(notifier)
    executor = make_executor(
        tool=tool,
        resolved_values={"source": "value"},
        client=client,
        output_destination_resolver=lambda *_args, **_kwargs: output_path,
    )

    revealed_paths: List[Path] = []
    clipboard_payloads: List[str] = []
    monkeypatch.setattr(executor, "_plugin_interface", lambda: plugin)
    monkeypatch.setattr(
        "nextgis_toolbox.processing.toolbox_task_executor.reveal_in_file_manager",
        revealed_paths.append,
    )
    monkeypatch.setattr(
        "nextgis_toolbox.processing.toolbox_task_executor.set_clipboard_data",
        lambda mime_type, data, text: clipboard_payloads.append(text),
    )

    executor.execute({}, object(), FakeFeedback())

    assert len(notifier.messages) == 1
    assert notifier.messages[0]["duration"] == 0
    widgets = notifier.messages[0]["widgets"]
    assert widgets is not None
    assert [widget.text() for widget in widgets] == [
        "Show file",
        "Copy path",
    ]

    reveal_button = widgets[0]
    copy_button = widgets[1]
    assert isinstance(reveal_button, QPushButton)
    assert isinstance(copy_button, QPushButton)

    reveal_button.click()
    copy_button.click()

    assert revealed_paths == [output_path]
    assert clipboard_payloads == [str(output_path)]


def test_execute_prefers_injected_notifier_over_plugin_notifier(
    tmp_path: Path,
    monkeypatch,
) -> None:
    output_path = tmp_path / "result.zip"
    tool = make_tool(
        make_parameter("source", "string"),
        outputs=[make_output_parameter("result", "file")],
    )
    client = FakeApiClient(
        tasks=[
            make_task(
                TaskStatus.SUCCESS,
                progress=1.0,
                results=[
                    TaskResult(
                        name="result",
                        value="storage/result-1",
                    )
                ],
            )
        ]
    )
    dialog_notifier = FakeNotifier()
    plugin_notifier = FakeNotifier()
    plugin = FakePluginInterface(plugin_notifier)
    executor = make_executor(
        tool=tool,
        resolved_values={"source": "value"},
        client=client,
        notifier=dialog_notifier,
        output_destination_resolver=lambda *_args, **_kwargs: output_path,
    )

    monkeypatch.setattr(executor, "_plugin_interface", lambda: plugin)

    executor.execute({}, object(), FakeFeedback())

    assert len(dialog_notifier.messages) == 1
    assert plugin_notifier.messages == []


def test_result_destination_path_infers_extension_for_placeholder_name() -> (
    None
):
    tool = make_tool(
        make_parameter("source", "string"),
        outputs=[make_output_parameter("result_file", "file")],
    )
    executor = make_executor(
        tool=tool,
        resolved_values={"source": "value"},
        client=FakeApiClient(),
    )

    destination_path = executor._result_destination_path(
        "task-1",
        TaskResult(
            name="result_file.file",
            value="storage/server-result.gpkg",
        ),
        tool.outputs[0],
        {},
        object(),
    )

    assert destination_path == (
        executor._temporary_download_directory("task-1") / "result_file.gpkg"
    )


def test_result_destination_path_treats_zip_alias_as_zip_archive() -> None:
    tool = make_tool(
        make_parameter("source", "string"),
        outputs=[
            make_output_parameter(
                "geometry",
                "file",
                alias="Geometry zip",
            )
        ],
    )
    executor = make_executor(
        tool=tool,
        resolved_values={"source": "value"},
        client=FakeApiClient(),
    )

    destination_path = executor._result_destination_path(
        "task-1",
        TaskResult(
            name="geometry.file",
            value="storage/result-1",
        ),
        tool.outputs[0],
        {},
        object(),
    )

    assert destination_path == (
        executor._temporary_download_directory("task-1") / "geometry.zip"
    )


def test_result_destination_path_treats_russian_zip_alias_as_zip_archive() -> (
    None
):
    tool = make_tool(
        make_parameter("source", "string"),
        outputs=[
            make_output_parameter(
                "geometry",
                "file",
                alias="Файл GeoPackage в ZIP-архиве",
            )
        ],
    )
    executor = make_executor(
        tool=tool,
        resolved_values={"source": "value"},
        client=FakeApiClient(),
    )

    destination_path = executor._result_destination_path(
        "task-1",
        TaskResult(
            name="geometry.file",
            value="storage/result-1",
        ),
        tool.outputs[0],
        {},
        object(),
    )

    assert destination_path == (
        executor._temporary_download_directory("task-1") / "geometry.zip"
    )


def test_result_destination_path_treats_english_zip_archive_alias_as_zip() -> (
    None
):
    tool = make_tool(
        make_parameter("source", "string"),
        outputs=[
            make_output_parameter(
                "geometry",
                "file",
                alias="GeoPackage file in ZIP archive",
            )
        ],
    )
    executor = make_executor(
        tool=tool,
        resolved_values={"source": "value"},
        client=FakeApiClient(),
    )

    destination_path = executor._result_destination_path(
        "task-1",
        TaskResult(
            name="geometry.file",
            value="storage/result-1",
        ),
        tool.outputs[0],
        {},
        object(),
    )

    assert destination_path == (
        executor._temporary_download_directory("task-1") / "geometry.zip"
    )


def test_result_destination_path_normalizes_placeholder_from_resolver(
    tmp_path: Path,
) -> None:
    tool = make_tool(
        make_parameter("source", "string"),
        outputs=[
            make_output_parameter(
                "geometry",
                "file",
                alias="GeoPackage file in ZIP archive",
            )
        ],
    )
    executor = make_executor(
        tool=tool,
        resolved_values={"source": "value"},
        client=FakeApiClient(),
        output_destination_resolver=lambda *_args, **_kwargs: (
            tmp_path / "geometry.file"
        ),
    )

    destination_path = executor._result_destination_path(
        "task-1",
        TaskResult(
            name="geometry.file",
            value="storage/result-1",
        ),
        tool.outputs[0],
        {},
        object(),
    )

    assert destination_path == tmp_path / "geometry.zip"


def test_load_output_layers_queries_archive_members_and_sublayers(
    tmp_path: Path,
    monkeypatch,
) -> None:
    output_path = tmp_path / "result.zip"
    with ZipFile(output_path, "w") as archive:
        archive.writestr("nested/result.gpkg", "")

    queried_sources: List[str] = []
    attempted_sources: List[str] = []

    class FakeSublayerDetail:
        def __init__(self, uri: str, name: str) -> None:
            self._uri = uri
            self._name = name

        def uri(self) -> str:
            return self._uri

        def name(self) -> str:
            return self._name

    class FakeProviderRegistry:
        def querySublayers(self, source: str) -> List[FakeSublayerDetail]:
            queried_sources.append(source)
            if source.endswith("/nested/result.gpkg"):
                return [
                    FakeSublayerDetail(
                        f"{source}|layername=roads",
                        "result.gpkg",
                    ),
                    FakeSublayerDetail(
                        f"{source}|layername=buildings",
                        "result.gpkg",
                    ),
                ]

            return []

    class FakeProviderRegistryClass:
        @classmethod
        def instance(cls) -> FakeProviderRegistry:
            del cls
            return FakeProviderRegistry()

    class FakeVectorLayer:
        def __init__(self, source: str, name: str, provider: str) -> None:
            del name, provider
            attempted_sources.append(source)
            self._source = source

        def isValid(self) -> bool:
            return "|layername=" in self._source

    class FakeRasterLayer:
        def __init__(self, source: str, name: str) -> None:
            del name
            attempted_sources.append(source)

        def isValid(self) -> bool:
            return False

    monkeypatch.setattr(
        "nextgis_toolbox.processing.toolbox_task_executor.QgsProviderRegistry",
        FakeProviderRegistryClass,
    )
    monkeypatch.setattr(
        "nextgis_toolbox.processing.toolbox_task_executor.QgsVectorLayer",
        FakeVectorLayer,
    )
    monkeypatch.setattr(
        "nextgis_toolbox.processing.toolbox_task_executor.QgsRasterLayer",
        FakeRasterLayer,
    )

    executor = make_executor(
        tool=make_tool(make_parameter("source", "string")),
        resolved_values={"source": "value"},
        client=FakeApiClient(),
    )

    layers = executor._load_output_layers("result", output_path)

    assert len(layers) == 2
    assert f"/vsizip/{output_path}" in queried_sources
    assert f"/vsizip/{output_path}/nested/result.gpkg" in queried_sources
    assert (
        f"/vsizip/{output_path}/nested/result.gpkg|layername=roads"
        in attempted_sources
    )
    assert (
        f"/vsizip/{output_path}/nested/result.gpkg|layername=buildings"
        in attempted_sources
    )


def test_load_output_layers_uses_archive_members_without_sublayers(
    tmp_path: Path,
    monkeypatch,
) -> None:
    output_path = tmp_path / "result.zip"
    with ZipFile(output_path, "w") as archive:
        archive.writestr("nested/result.shp", "")
        archive.writestr("nested/result.tif", "")

    queried_sources: List[str] = []
    attempted_sources: List[str] = []

    class FakeProviderRegistry:
        def querySublayers(self, source: str) -> List[object]:
            queried_sources.append(source)
            return []

    class FakeProviderRegistryClass:
        @classmethod
        def instance(cls) -> FakeProviderRegistry:
            del cls
            return FakeProviderRegistry()

    class FakeVectorLayer:
        def __init__(self, source: str, name: str, provider: str) -> None:
            del name, provider
            attempted_sources.append(source)
            self._source = source

        def isValid(self) -> bool:
            return self._source.endswith("result.shp")

    class FakeRasterLayer:
        def __init__(self, source: str, name: str) -> None:
            del name
            attempted_sources.append(source)
            self._source = source

        def isValid(self) -> bool:
            return self._source.endswith("result.tif")

    monkeypatch.setattr(
        "nextgis_toolbox.processing.toolbox_task_executor.QgsProviderRegistry",
        FakeProviderRegistryClass,
    )
    monkeypatch.setattr(
        "nextgis_toolbox.processing.toolbox_task_executor.QgsVectorLayer",
        FakeVectorLayer,
    )
    monkeypatch.setattr(
        "nextgis_toolbox.processing.toolbox_task_executor.QgsRasterLayer",
        FakeRasterLayer,
    )

    executor = make_executor(
        tool=make_tool(make_parameter("source", "string")),
        resolved_values={"source": "value"},
        client=FakeApiClient(),
    )

    layers = executor._load_output_layers("result", output_path)

    assert len(layers) == 2
    assert f"/vsizip/{output_path}" in queried_sources
    assert f"/vsizip/{output_path}/nested/result.shp" in attempted_sources
    assert f"/vsizip/{output_path}/nested/result.tif" in attempted_sources


def test_execute_shows_single_warning_when_outputs_are_not_added(
    tmp_path: Path,
    monkeypatch,
) -> None:
    output_path = tmp_path / "result.zip"
    tool = make_tool(
        make_parameter("source", "string"),
        outputs=[make_output_parameter("result", "file")],
    )
    client = FakeApiClient(
        tasks=[
            make_task(
                TaskStatus.SUCCESS,
                progress=1.0,
                results=[
                    TaskResult(
                        name="result",
                        value="storage/result-1",
                    )
                ],
            )
        ]
    )
    notifier = FakeNotifier()
    feedback = FakeFeedback()
    executor = make_executor(
        tool=tool,
        resolved_values={"source": "value"},
        client=client,
        notifier=notifier,
        output_destination_resolver=lambda *_args, **_kwargs: output_path,
    )
    monkeypatch.setattr(
        executor,
        "_load_output_layer",
        lambda *_args, **_kwargs: None,
    )

    result = executor.execute(
        {},
        object(),
        feedback,
        add_to_project=True,
    )

    assert result == {"result": str(output_path)}
    assert len(notifier.messages) == 1
    assert notifier.messages[0]["duration"] == 0
    assert notifier.messages[0]["level"] == Qgis.MessageLevel.Warning
    assert "Downloaded 1 output file(s)." in notifier.messages[0]["message"]
    assert (
        "Some output files were not added to the project"
        in (notifier.messages[0]["message"])
    )
    assert any(
        "Some output files were not added to the project" in info
        for info in feedback.infos
    )


def test_show_warning_message_keeps_result_notification_visible() -> None:
    tool = make_tool(make_parameter("source", "string"))
    notifier = FakeNotifier()
    executor = make_executor(
        tool=tool,
        resolved_values={"source": "value"},
        client=FakeApiClient(),
        notifier=notifier,
    )

    executor._show_warning_message(
        "Some output files were not added to the project.",
        FakeFeedback(),
    )

    assert notifier.messages[0]["duration"] == 0


def test_execute_raises_task_failed_error_for_failed_status() -> None:
    tool = make_tool(make_parameter("source", "string"))
    client = FakeApiClient(tasks=[make_task(TaskStatus.FAILED, error="boom")])
    executor = make_executor(
        tool=tool,
        resolved_values={"source": "value"},
        client=client,
    )

    with pytest.raises(ToolboxTaskFailedError) as error:
        executor.execute({}, object(), FakeFeedback())

    assert "status=FAILED" in str(error.value)
    assert "error=boom" in str(error.value)


@pytest.mark.parametrize(
    ("status", "text"),
    [
        (TaskStatus.DENIED, "Task failed"),
        (TaskStatus.CANCELLED, "Task canceled"),
        (TaskStatus.TIMEOUT, "Task timed out"),
    ],
)
def test_execute_raises_for_terminal_error_statuses(
    status: TaskStatus,
    text: str,
) -> None:
    tool = make_tool(make_parameter("source", "string"))
    client = FakeApiClient(tasks=[make_task(status, error="server-error")])
    feedback = FakeFeedback()
    executor = make_executor(
        tool=tool,
        resolved_values={"source": "value"},
        client=client,
    )

    with pytest.raises(ToolboxTaskFailedError):
        executor.execute({}, object(), feedback)

    assert text in feedback.progress_texts


def test_execute_tolerates_unknown_status_then_recovers() -> None:
    tool = make_tool(make_parameter("source", "string"))
    client = FakeApiClient(
        tasks=[
            make_task(TaskStatus.UNKNOWN, progress=None),
            make_task(TaskStatus.STARTED, progress=0.25),
            make_task(TaskStatus.SUCCESS, progress=1.0),
        ]
    )
    clock = FakeClock()
    executor = make_executor(
        tool=tool,
        resolved_values={"source": "value"},
        client=client,
        clock=clock,
    )

    result = executor.execute({}, object(), FakeFeedback())

    assert result == {}
    assert clock.sleep_calls == [1.0, 1.0]


def test_execute_raises_when_unknown_status_exceeds_grace_period() -> None:
    tool = make_tool(make_parameter("source", "string"))
    client = FakeApiClient(
        tasks=[
            make_task(TaskStatus.UNKNOWN, progress=None),
            make_task(TaskStatus.UNKNOWN, progress=None),
            make_task(TaskStatus.UNKNOWN, progress=None),
            make_task(TaskStatus.UNKNOWN, progress=None),
        ]
    )
    clock = FakeClock()
    executor = make_executor(
        tool=tool,
        resolved_values={"source": "value"},
        client=client,
        clock=clock,
    )

    with pytest.raises(ToolboxTaskExecutionError) as error:
        executor.execute({}, object(), FakeFeedback())

    assert "UNKNOWN status" in str(error.value)
    assert clock.sleep_calls == [1.0, 2.0, 3.0]


def test_execute_returns_empty_dict_when_user_cancels_polling() -> None:
    tool = make_tool(make_parameter("source", "string"))
    client = FakeApiClient(
        tasks=[
            make_task(TaskStatus.NEW, progress=0.0),
            make_task(TaskStatus.ASSIGNED, progress=0.0),
        ]
    )
    feedback = FakeFeedback(cancel_after_checks=2)
    clock = FakeClock()
    executor = make_executor(
        tool=tool,
        resolved_values={"source": "value"},
        client=client,
        clock=clock,
    )

    result = executor.execute({}, object(), feedback)

    assert result == {}
    assert feedback.infos == [
        "Execution was canceled. The task continues on the server side."
    ]
    assert clock.sleep_calls == []


def test_execute_raises_client_side_wait_timeout() -> None:
    tool = make_tool(make_parameter("source", "string"))
    client = FakeApiClient(
        tasks=[
            make_task(TaskStatus.STARTED, progress=0.1),
            make_task(TaskStatus.STARTED, progress=0.2),
        ]
    )
    clock = FakeClock()
    executor = make_executor(
        tool=tool,
        resolved_values={"source": "value"},
        client=client,
        clock=clock,
        wait_timeout_seconds=0.5,
    )

    with pytest.raises(ToolboxTaskTimeoutError):
        executor.execute({}, object(), FakeFeedback())

    assert clock.sleep_calls == [1.0]


def test_execute_uploads_single_input_file(tmp_path: Path) -> None:
    source_path = tmp_path / "input.txt"
    source_path.write_text("payload", encoding="utf-8")

    tool = make_tool(make_parameter("source_file", "file"))
    uploaded_value = make_file_reference("input.txt", "uuid-1")
    client = FakeApiClient(
        tasks=[make_task(TaskStatus.SUCCESS, progress=1.0)],
        upload_responses=[uploaded_value],
    )
    executor = make_executor(
        tool=tool,
        resolved_values={"source_file": source_path},
        client=client,
    )

    executor.execute({}, object(), FakeFeedback())

    assert client.uploaded_paths == [source_path]
    assert client.submitted_inputs == [{"source_file": uploaded_value}]


def test_execute_uploads_list_of_input_files(tmp_path: Path) -> None:
    first_path = tmp_path / "a.txt"
    second_path = tmp_path / "b.txt"
    first_path.write_text("a", encoding="utf-8")
    second_path.write_text("b", encoding="utf-8")

    tool = make_tool(make_parameter("source_files", "file"))
    first_upload = make_file_reference("a.txt", "uuid-a")
    second_upload = make_file_reference("b.txt", "uuid-b")
    client = FakeApiClient(
        tasks=[make_task(TaskStatus.SUCCESS, progress=1.0)],
        upload_responses=[first_upload, second_upload],
    )
    executor = make_executor(
        tool=tool,
        resolved_values={"source_files": [first_path, second_path]},
        client=client,
    )

    executor.execute({}, object(), FakeFeedback())

    assert client.uploaded_paths == [first_path, second_path]
    assert client.submitted_inputs == [
        {"source_files": [first_upload, second_upload]}
    ]


def test_execute_skips_optional_file_upload_when_value_is_empty() -> None:
    tool = make_tool(make_parameter("source_file", "file", required=False))
    client = FakeApiClient(tasks=[make_task(TaskStatus.SUCCESS, progress=1.0)])
    executor = make_executor(
        tool=tool,
        resolved_values={"source_file": None},
        client=client,
    )

    executor.execute({}, object(), FakeFeedback())

    assert client.uploaded_paths == []
    assert client.submitted_inputs == [{"source_file": None}]


def test_execute_raises_for_missing_input_file(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing.txt"
    tool = make_tool(make_parameter("source_file", "file"))
    client = FakeApiClient(tasks=[make_task(TaskStatus.SUCCESS, progress=1.0)])
    executor = make_executor(
        tool=tool,
        resolved_values={"source_file": missing_path},
        client=client,
    )

    with pytest.raises(ToolboxFileUploadError):
        executor.execute({}, object(), FakeFeedback())

    assert client.submitted_inputs == []


def test_execute_raises_for_upload_api_error(tmp_path: Path) -> None:
    source_path = tmp_path / "input.txt"
    source_path.write_text("payload", encoding="utf-8")

    tool = make_tool(make_parameter("source_file", "file"))
    client = FakeApiClient(
        tasks=[make_task(TaskStatus.SUCCESS, progress=1.0)],
        upload_responses=[RuntimeError("upload failed")],
    )
    executor = make_executor(
        tool=tool,
        resolved_values={"source_file": source_path},
        client=client,
    )

    with pytest.raises(ToolboxFileUploadError):
        executor.execute({}, object(), FakeFeedback())


def test_execute_clamps_progress_above_one(monkeypatch) -> None:
    tool = make_tool(make_parameter("source", "string"))
    client = FakeApiClient(
        tasks=[
            make_task(TaskStatus.STARTED, progress=1.2),
            make_task(TaskStatus.SUCCESS, progress=1.0),
        ]
    )
    clock = FakeClock()
    executor = make_executor(
        tool=tool,
        resolved_values={"source": "value"},
        client=client,
        clock=clock,
    )

    warning_messages: List[str] = []
    monkeypatch.setattr(
        "nextgis_toolbox.processing.toolbox_task_executor.logger.warning",
        warning_messages.append,
    )

    executor.execute({}, object(), FakeFeedback())

    assert any(
        "reported progress above 1.0" in message
        for message in warning_messages
    )


def test_execute_ignores_missing_progress_until_terminal_state() -> None:
    tool = make_tool(make_parameter("source", "string"))
    client = FakeApiClient(
        tasks=[
            make_task(TaskStatus.STARTED, progress=None),
            make_task(TaskStatus.SUCCESS, progress=1.0),
        ]
    )
    feedback = FakeFeedback()
    clock = FakeClock()
    executor = make_executor(
        tool=tool,
        resolved_values={"source": "value"},
        client=client,
        clock=clock,
    )

    executor.execute({}, object(), feedback)

    assert feedback.progress_values == [100]
    assert clock.sleep_calls == [1.0]


def test_executor_module_does_not_import_requests_directly() -> None:
    module = importlib.import_module(
        "nextgis_toolbox.processing.toolbox_task_executor"
    )
    module_path = Path(module.__file__)
    source = module_path.read_text(encoding="utf-8")

    assert "import requests" not in source
    assert "requests." not in source
