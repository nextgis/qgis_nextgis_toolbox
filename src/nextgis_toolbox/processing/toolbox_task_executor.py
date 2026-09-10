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

import html
import re
from dataclasses import dataclass
from math import ceil
from pathlib import Path
from pprint import pformat
from tempfile import mkdtemp
from time import monotonic, sleep
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit
from zipfile import BadZipFile, ZipFile

from qgis.core import (
    Qgis,
    QgsMapLayer,
    QgsProcessingContext,
    QgsProcessingFeedback,
    QgsProject,
    QgsProviderRegistry,
    QgsRasterLayer,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QCoreApplication, QThread, QUrl
from qgis.PyQt.QtWidgets import QPushButton, QWidget

from nextgis_toolbox.api.client import ToolboxApiClient
from nextgis_toolbox.core.compat import QGIS_3_36
from nextgis_toolbox.core.exceptions import (
    ToolboxError,
    ToolboxFileUploadError,
    ToolboxRequestCanceledError,
    ToolboxTaskExecutionError,
    ToolboxTaskFailedError,
    ToolboxTaskTimeoutError,
)
from nextgis_toolbox.core.logging import logger
from nextgis_toolbox.core.utils import set_clipboard_data
from nextgis_toolbox.nextgis_toolbox_interface import (
    NextgisToolboxInterface,
)
from nextgis_toolbox.notifier.notifier_interface import NotifierInterface
from nextgis_toolbox.processing.parameters.resolvers import (
    OutputDestinationResolver,
    ParameterValueResolver,
)
from nextgis_toolbox.processing.task_polling_policy import (
    TaskExecutionSnapshot,
    TaskExecutionState,
    TaskPollingPolicy,
)
from nextgis_toolbox.shared.filesystem import reveal_in_file_manager
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

_PENDING_STATUSES = (
    TaskStatus.NEW,
    TaskStatus.ASSIGNED,
    TaskStatus.ACCEPTED,
)
_FAILED_STATUSES = (
    TaskStatus.FAILED,
    TaskStatus.DENIED,
    TaskStatus.CANCELLED,
    TaskStatus.TIMEOUT,
)
_REMOTE_FILE_PREFIXES = (
    "http://",
    "https://",
    "storage/",
    "download/",
    "api/",
    "/api/",
    "/download/",
)
_DEFAULT_WAIT_TIMEOUT_SECONDS = 24.0 * 60.0 * 60.0
_ARCHIVED_VECTOR_EXTENSIONS = (
    ".csv",
    ".geojson",
    ".gml",
    ".gpkg",
    ".gpx",
    ".json",
    ".kml",
    ".mif",
    ".shp",
    ".sqlite",
    ".tab",
)
_ARCHIVED_RASTER_EXTENSIONS = (
    ".asc",
    ".bil",
    ".grd",
    ".img",
    ".jp2",
    ".nc",
    ".tif",
    ".tiff",
    ".vrt",
)
_ZIP_ALIAS_PATTERN = re.compile(r"(^|[ -])zip($|[ -])", re.IGNORECASE)
TaskSubmitter = Callable[
    [str, Dict[str, Any], bool, QgsProcessingFeedback], str
]
TaskInformationResolver = Callable[
    [str, QgsProcessingFeedback],
    ToolboxTaskInformation,
]
TaskResultsUrlResolver = Callable[[str], str]
MonotonicClock = Callable[[], float]
Sleeper = Callable[[float], None]


@dataclass(frozen=True)
class _UploadJob:
    parameter_name: str
    path: Path
    value_index: Optional[int]


@dataclass(frozen=True)
class _OutputImportSummary:
    added_layer_count: int
    skipped_paths: Tuple[Path, ...]


@dataclass(frozen=True)
class _LayerLoadCandidate:
    source: str
    name: str


class ToolboxTaskExecutor:
    """Execute a Toolbox tool and wait for its server-side task."""

    def __init__(
        self,
        api_client: ToolboxApiClient,
        task_submitter: TaskSubmitter,
        task_information_resolver: TaskInformationResolver,
        task_results_url_resolver: TaskResultsUrlResolver,
        tool: ToolboxTool,
        parameter_resolver: ParameterValueResolver,
        *,
        notifier: Optional[NotifierInterface] = None,
        output_destination_resolver: Optional[
            OutputDestinationResolver
        ] = None,
        polling_policy: Optional[TaskPollingPolicy] = None,
        monotonic_clock: MonotonicClock = monotonic,
        sleeper: Sleeper = sleep,
        wait_timeout_seconds: Optional[float] = _DEFAULT_WAIT_TIMEOUT_SECONDS,
        unknown_status_poll_limit: int = 3,
        unknown_status_grace_seconds: float = 60.0,
    ) -> None:
        """Initialize executor."""
        self._api_client = api_client
        self._task_submitter = task_submitter
        self._task_information_resolver = task_information_resolver
        self._task_results_url_resolver = task_results_url_resolver
        self._tool = tool
        self._parameter_resolver = parameter_resolver
        self._notifier = notifier
        self._output_destination_resolver = output_destination_resolver
        self._polling_policy = polling_policy or TaskPollingPolicy()
        self._monotonic = monotonic_clock
        self._sleeper = sleeper
        self._wait_timeout_seconds = wait_timeout_seconds
        self._unknown_status_poll_limit = unknown_status_poll_limit
        self._unknown_status_grace_seconds = unknown_status_grace_seconds
        self._temporary_results_directory: Optional[Path] = None

    def execute(
        self,
        parameters: Dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
        *,
        emailing: bool = False,
        add_to_project: bool = False,
    ) -> Dict[str, Any]:
        """Execute the tool and wait for completion."""
        logger.info(f"Running tool '{self._tool.name}'")

        try:
            self._set_execution_state(
                feedback,
                TaskExecutionState.PREPARING,
                backend_status=TaskStatus.UNKNOWN,
            )

            resolved_parameters = self._prepare_parameters(parameters, context)
            if self._cancel_if_requested(feedback, task_id=None):
                return {}

            upload_jobs = self._collect_upload_jobs(resolved_parameters)
            if upload_jobs:
                self._set_execution_state(
                    feedback,
                    TaskExecutionState.UPLOADING,
                    backend_status=TaskStatus.UNKNOWN,
                )
                self._upload_input_files(
                    resolved_parameters,
                    upload_jobs,
                    feedback,
                )
                if self._cancel_if_requested(feedback, task_id=None):
                    return {}

            self._set_execution_state(
                feedback,
                TaskExecutionState.SUBMITTING,
                backend_status=TaskStatus.UNKNOWN,
            )
            task_id = self._submit_task(
                resolved_parameters,
                feedback,
                emailing=emailing,
            )
        except ToolboxRequestCanceledError as error:
            if self._cancel_if_requested(feedback, task_id=None):
                return {}
            wrapped_error = ToolboxTaskExecutionError(
                log_message=(
                    f"Task setup was canceled unexpectedly for tool '{self._tool.name}'"
                ),
            )
            wrapped_error.add_note(f"Technical details: {error}")
            raise wrapped_error from error

        return self._wait_for_completion(
            task_id,
            parameters,
            context,
            feedback,
            add_to_project=add_to_project,
        )

    def _prepare_parameters(
        self,
        parameters: Dict[str, Any],
        context: QgsProcessingContext,
    ) -> Dict[str, Any]:
        """Prepare runtime input values for the Toolbox API."""
        resolved_parameters: Dict[str, Any] = {}

        for parameter in self._tool.inputs:
            try:
                value = self._parameter_resolver(
                    parameter, parameters, context
                )
            except Exception as error:
                logger.exception(
                    "Failed to resolve Processing parameter "
                    f"'{parameter.name}' for tool '{self._tool.name}'",
                    exc_info=error,
                )
                wrapped_error = ToolboxTaskExecutionError(
                    log_message=(
                        "Failed to prepare task parameter "
                        f"'{parameter.name}' for tool '{self._tool.name}'"
                    ),
                )
                wrapped_error.add_note(f"Technical details: {error}")
                raise wrapped_error from error

            if parameter.parameter_type == InputParameterType.FILE:
                value = self._normalize_file_value(parameter, value)

            resolved_parameters[parameter.name] = value

        return resolved_parameters

    def _collect_upload_jobs(
        self,
        resolved_parameters: Dict[str, Any],
    ) -> List[_UploadJob]:
        """Collect all file uploads required for the task."""
        upload_jobs: List[_UploadJob] = []

        for parameter in self._tool.inputs:
            if parameter.parameter_type != InputParameterType.FILE:
                continue

            value = resolved_parameters.get(parameter.name)
            if isinstance(value, list):
                for index, item in enumerate(value):
                    if isinstance(item, Path):
                        upload_jobs.append(
                            _UploadJob(parameter.name, item, index)
                        )
                continue

            if isinstance(value, Path):
                upload_jobs.append(_UploadJob(parameter.name, value, None))

        return upload_jobs

    def _upload_input_files(
        self,
        resolved_parameters: Dict[str, Any],
        upload_jobs: Sequence[_UploadJob],
        feedback: QgsProcessingFeedback,
    ) -> None:
        """Upload local input files to the Toolbox server."""
        total_files = len(upload_jobs)
        feedback.setProgressText(self.tr("Uploading input files..."))
        logger.info(
            f"Uploading {total_files} input file(s) for tool '{self._tool.name}'"
        )

        for index, upload_job in enumerate(upload_jobs, start=1):
            file_name = upload_job.path.name
            message = self.tr(
                "Uploading file {current} of {total}: {name}"
            ).format(
                current=index,
                total=total_files,
                name=file_name,
            )
            feedback.setProgressText(message)
            logger.info(
                "Uploading input file "
                f"{index}/{total_files} for parameter "
                f"'{upload_job.parameter_name}': '{upload_job.path}'"
            )

            try:
                uploaded_value = self._api_client.upload(
                    upload_job.path,
                    feedback=feedback,
                )
            except ToolboxRequestCanceledError:
                raise
            except ToolboxFileUploadError:
                raise
            except Exception as error:
                logger.exception(
                    f"Failed to upload '{upload_job.path}'",
                    exc_info=error,
                )
                wrapped_error = ToolboxFileUploadError(
                    log_message=(
                        "Failed to upload input file for parameter "
                        f"'{upload_job.parameter_name}'"
                    ),
                    detail=str(upload_job.path),
                )
                wrapped_error.add_note(f"Technical details: {error}")
                raise wrapped_error from error

            if not self._is_server_file_reference(uploaded_value):
                wrapped_error = ToolboxFileUploadError(
                    log_message=(
                        "Upload did not return a valid file reference for "
                        f"parameter '{upload_job.parameter_name}'"
                    ),
                )
                wrapped_error.add_note(f"Response payload: {uploaded_value}")
                raise wrapped_error

            logger.info(
                f"Uploaded input file '{upload_job.path}' successfully"
            )
            self._apply_uploaded_value(
                resolved_parameters,
                upload_job,
                uploaded_value,
            )

        feedback.setProgressText(self.tr("Submitting task..."))

    def _submit_task(
        self,
        resolved_parameters: Dict[str, Any],
        feedback: QgsProcessingFeedback,
        *,
        emailing: bool,
    ) -> str:
        """Submit the Toolbox task to the server."""
        try:
            task_id = self._task_submitter(
                self._tool.name,
                resolved_parameters,
                emailing,
                feedback,
            )
        except ToolboxRequestCanceledError:
            raise
        except ToolboxTaskExecutionError:
            raise
        except Exception as error:
            logger.exception(
                f"Failed to submit task for tool '{self._tool.name}'",
                exc_info=error,
            )
            wrapped_error = ToolboxTaskExecutionError(
                log_message=(
                    f"Failed to submit task for tool '{self._tool.name}'"
                ),
            )
            wrapped_error.add_note(f"Technical details: {error}")
            raise wrapped_error from error

        logger.info(f"Submitted task '{task_id}' for tool '{self._tool.name}'")
        return task_id

    def _wait_for_completion(
        self,
        task_id: str,
        parameters: Dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
        *,
        add_to_project: bool,
    ) -> Dict[str, Any]:
        """Poll the server until the task reaches a terminal state."""
        started_at = self._monotonic()
        previous_status = TaskStatus.UNKNOWN
        previous_state: Optional[TaskExecutionState] = None
        previous_progress: Optional[float] = None
        state_started_at = started_at
        state_poll_count = 0
        consecutive_unknown_polls = 0
        unknown_started_at: Optional[float] = None
        has_polled = False

        while True:
            if self._cancel_if_requested(feedback, task_id=task_id):
                return {}

            if has_polled:
                self._raise_if_wait_timeout_exceeded(task_id, started_at)

            try:
                task = self._task_information_resolver(
                    task_id,
                    feedback,
                )
            except ToolboxRequestCanceledError:
                if self._cancel_if_requested(feedback, task_id=task_id):
                    return {}
                raise
            except Exception as error:
                logger.exception(
                    f"Failed to retrieve task '{task_id}' status",
                    exc_info=error,
                )
                wrapped_error = ToolboxTaskExecutionError(
                    log_message=(
                        f"Failed to retrieve task '{task_id}' status"
                    ),
                )
                wrapped_error.add_note(f"Technical details: {error}")
                raise wrapped_error from error

            has_polled = True
            now = self._monotonic()
            normalized_progress = self._normalize_progress(task, task_id)
            execution_state = self._map_execution_state(
                task,
                normalized_progress,
                previous_state,
            )
            snapshot = TaskExecutionSnapshot(
                task_id=task_id,
                backend_status=task.status,
                execution_state=execution_state,
                progress=normalized_progress,
                error=task.error,
                elapsed_seconds=now - started_at,
            )

            if task.status == TaskStatus.UNKNOWN:
                consecutive_unknown_polls += 1
                if unknown_started_at is None:
                    unknown_started_at = now
                self._raise_if_unknown_status_exceeded(
                    snapshot,
                    consecutive_unknown_polls,
                    unknown_started_at,
                )
            else:
                consecutive_unknown_polls = 0
                unknown_started_at = None

            if task.status != previous_status:
                logger.debug(
                    f"Task '{task_id}' status changed: "
                    f"{previous_status} -> {task.status}"
                )
                feedback.pushDebugInfo(
                    "Task status changed: "
                    f"{previous_status.value} -> {task.status.value}"
                )
                previous_status = task.status

            if execution_state != previous_state:
                logger.debug(
                    f"Task '{task_id}' execution state changed: "
                    f"{previous_state} -> {execution_state}"
                )
                state_started_at = now
                state_poll_count = 1
                previous_state = execution_state
                self._set_execution_state(
                    feedback,
                    execution_state,
                    backend_status=task.status,
                )
            else:
                state_poll_count += 1

            previous_progress = self._update_progress(
                feedback,
                task_id,
                execution_state,
                normalized_progress,
                previous_progress,
            )

            if task.status == TaskStatus.SUCCESS:
                processing_results, downloaded_paths = (
                    self._prepare_processing_results(
                        task_id,
                        task,
                        parameters,
                        context,
                        feedback,
                    )
                )
                output_import_summary = _OutputImportSummary(0, ())
                if add_to_project:
                    output_import_summary = (
                        self._add_downloaded_outputs_to_project(
                            downloaded_paths,
                        )
                    )
                logger.info(f"Tool '{self._tool.name}' finished successfully")
                self._report_success(
                    task_id,
                    task,
                    feedback,
                    downloaded_paths,
                )
                self._show_completion_message(
                    downloaded_paths,
                    output_import_summary,
                    feedback,
                )
                return processing_results

            if task.status in _FAILED_STATUSES:
                self._raise_task_failed(task_id, task)

            self._raise_if_wait_timeout_exceeded(task_id, started_at)
            if self._cancel_if_requested(feedback, task_id=task_id):
                return {}

            interval = self._polling_policy.next_interval(
                snapshot,
                state_elapsed_seconds=now - state_started_at,
                state_poll_count=state_poll_count,
            )
            self._sleeper(interval)

    def _normalize_file_value(
        self,
        parameter: ToolInputParameter,
        value: Any,
    ) -> Any:
        """Normalize a file parameter value before upload planning."""
        if isinstance(value, (list, tuple)):
            return [
                self._normalize_single_file_item(parameter, item)
                for item in value
            ]

        return self._normalize_single_file_item(parameter, value)

    def _normalize_single_file_item(
        self,
        parameter: ToolInputParameter,
        value: Any,
    ) -> Any:
        """Normalize a single file parameter item."""
        if value is None:
            return self._empty_file_value(parameter)

        if isinstance(value, Path):
            return self._validate_local_file(parameter, value)

        if isinstance(value, str):
            normalized_value = value.strip()
            if not normalized_value:
                return self._empty_file_value(parameter)
            if self._looks_like_remote_file(normalized_value):
                return normalized_value
            return self._validate_local_file(parameter, Path(normalized_value))

        if self._is_server_file_reference(value):
            return value

        raise ToolboxFileUploadError(
            log_message=(
                "Unsupported file input value for parameter "
                f"'{parameter.name}'"
            ),
            detail=str(value),
        )

    def _empty_file_value(self, parameter: ToolInputParameter) -> None:
        """Return the empty representation for an optional file input."""
        if parameter.required:
            raise ToolboxFileUploadError(
                log_message=(
                    f"File input parameter '{parameter.name}' is required"
                ),
                detail=parameter.name,
            )

        return None

    def _validate_local_file(
        self,
        parameter: ToolInputParameter,
        value: Path,
    ) -> Path:
        """Validate a local file path before upload."""
        file_path = Path(value)
        if not file_path.exists():
            raise ToolboxFileUploadError(
                log_message=(
                    f"Input file '{file_path}' does not exist for "
                    f"parameter '{parameter.name}'"
                ),
                detail=str(file_path),
            )

        if file_path.is_dir():
            raise ToolboxFileUploadError(
                log_message=(
                    f"Input path '{file_path}' is a directory for "
                    f"parameter '{parameter.name}'"
                ),
                detail=str(file_path),
            )

        try:
            with file_path.open("rb"):
                pass
        except OSError as error:
            wrapped_error = ToolboxFileUploadError(
                log_message=(
                    f"Input file '{file_path}' is not readable for "
                    f"parameter '{parameter.name}'"
                ),
                detail=str(file_path),
            )
            wrapped_error.add_note(f"Technical details: {error}")
            raise wrapped_error from error

        return file_path

    def _apply_uploaded_value(
        self,
        resolved_parameters: Dict[str, Any],
        upload_job: _UploadJob,
        uploaded_value: Dict[str, Any],
    ) -> None:
        """Store an uploaded file reference back into the parameters."""
        if upload_job.value_index is None:
            resolved_parameters[upload_job.parameter_name] = uploaded_value
            return

        parameter_values = resolved_parameters.get(upload_job.parameter_name)
        if not isinstance(parameter_values, list):
            wrapped_error = ToolboxFileUploadError(
                log_message=(
                    "Expected a list of file values for parameter "
                    f"'{upload_job.parameter_name}'"
                ),
            )
            wrapped_error.add_note(
                f"Resolved parameter value: {parameter_values}"
            )
            raise wrapped_error

        parameter_values[upload_job.value_index] = uploaded_value

    def _normalize_progress(
        self,
        task: ToolboxTaskInformation,
        task_id: str,
    ) -> Optional[float]:
        """Normalize backend progress to the expected client range."""
        progress = task.progress
        if progress is None:
            return None

        if progress < 0.0:
            return None

        if progress > 1.0:
            logger.warning(
                f"Task '{task_id}' reported progress above 1.0: {progress}"
            )
            return 1.0

        return progress

    def _map_execution_state(
        self,
        task: ToolboxTaskInformation,
        progress: Optional[float],
        previous_state: Optional[TaskExecutionState],
    ) -> TaskExecutionState:
        """Map backend task status to the client execution state."""
        if task.status == TaskStatus.SUCCESS:
            return TaskExecutionState.SUCCESS

        if task.status in _FAILED_STATUSES:
            return TaskExecutionState.FAILED

        if progress is not None and progress >= 1.0:
            return TaskExecutionState.FINISHING

        if task.status in _PENDING_STATUSES:
            return TaskExecutionState.PENDING

        if task.status == TaskStatus.STARTED:
            return TaskExecutionState.RUNNING

        if previous_state is not None and previous_state in (
            TaskExecutionState.PENDING,
            TaskExecutionState.RUNNING,
            TaskExecutionState.FINISHING,
        ):
            return previous_state

        return TaskExecutionState.PENDING

    def _set_execution_state(
        self,
        feedback: QgsProcessingFeedback,
        execution_state: TaskExecutionState,
        *,
        backend_status: TaskStatus,
    ) -> None:
        """Update feedback text for the current execution state."""
        feedback.setProgressText(
            self._feedback_text(execution_state, backend_status)
        )

    def _feedback_text(
        self,
        execution_state: TaskExecutionState,
        backend_status: TaskStatus,
    ) -> str:
        """Return feedback text for an execution state."""
        if execution_state == TaskExecutionState.PREPARING:
            return self.tr("Preparing task parameters...")

        if execution_state == TaskExecutionState.UPLOADING:
            return self.tr("Uploading input files...")

        if execution_state == TaskExecutionState.SUBMITTING:
            return self.tr("Submitting task...")

        if execution_state == TaskExecutionState.PENDING:
            return self.tr("Task submitted, waiting for execution...")

        if execution_state == TaskExecutionState.RUNNING:
            return self.tr("Task is being executed...")

        if execution_state == TaskExecutionState.FINISHING:
            return self.tr("Finishing task...")

        if execution_state == TaskExecutionState.SUCCESS:
            return self.tr("Task completed successfully")

        if execution_state == TaskExecutionState.CANCELED_BY_USER:
            return self.tr("Execution was canceled")

        if backend_status == TaskStatus.TIMEOUT:
            return self.tr("Task timed out")

        if backend_status == TaskStatus.CANCELLED:
            return self.tr("Task canceled")

        return self.tr("Task failed")

    def _update_progress(
        self,
        feedback: QgsProcessingFeedback,
        task_id: str,
        execution_state: TaskExecutionState,
        progress: Optional[float],
        previous_progress: Optional[float],
    ) -> Optional[float]:
        """Update numeric feedback progress when it changes."""
        if execution_state in (
            TaskExecutionState.FINISHING,
            TaskExecutionState.SUCCESS,
        ):
            return previous_progress

        if progress is None or progress == previous_progress:
            return previous_progress

        feedback.setProgress(ceil(progress * 100))
        logger.debug(f"Task '{task_id}' progress updated: {progress:.3f}")

        return progress

    def _report_success(
        self,
        task_id: str,
        task: ToolboxTaskInformation,
        feedback: QgsProcessingFeedback,
        downloaded_paths: Dict[str, Path],
    ) -> None:
        """Report successful task completion to Processing feedback."""
        feedback.setProgress(100)
        feedback.pushDebugInfo(pformat(task.results))

        url = self._task_results_url_resolver(task_id)
        prefix = self.tr("Tool results.")
        output_text_lines = [
            self._saved_output_text(name, path)
            for name, path in downloaded_paths.items()
        ]
        output_html_lines = [
            self._saved_output_html(name, path)
            for name, path in downloaded_paths.items()
        ]
        text_suffix_parts = []
        html_suffix_parts = []

        if output_text_lines:
            text_suffix_parts.append(
                self.tr("Saved outputs:\n{paths}").format(
                    paths="\n".join(output_text_lines),
                )
            )
            html_suffix_parts.append(
                self.tr("Saved outputs:<br>{paths}").format(
                    paths="<br>".join(output_html_lines),
                )
            )

        text_suffix_parts.append(
            self.tr("You can view the results in browser:\n{url}").format(
                url=url,
            )
        )
        html_suffix_parts.append(
            self.tr(
                "You can view the results in <a href='{url}'>browser</a>"
            ).format(
                url=html.escape(url, quote=True),
            )
        )

        text_suffix = "\n\n".join(text_suffix_parts)
        html_suffix = "<br><br>".join(html_suffix_parts)

        if Qgis.versionInt() >= QGIS_3_36:
            feedback.pushFormattedMessage(
                prefix + "<br>" + html_suffix,
                prefix + "\n" + text_suffix,
            )
        else:
            feedback.pushInfo(prefix)
            feedback.pushInfo(text_suffix)

    def _prepare_processing_results(
        self,
        task_id: str,
        task: ToolboxTaskInformation,
        parameters: Dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> Tuple[Dict[str, Any], Dict[str, Path]]:
        processing_results: Dict[str, Any] = {}
        downloaded_paths: Dict[str, Path] = {}
        task_results = {
            task_result.name: task_result for task_result in task.results
        }

        for output_parameter in self._tool.outputs:
            task_result = task_results.get(output_parameter.name)
            if task_result is None:
                continue

            if self._is_file_result(task_result, output_parameter):
                saved_path = self._download_result_file(
                    task_id,
                    task_result,
                    output_parameter,
                    parameters,
                    context,
                )
                processing_results[output_parameter.name] = str(saved_path)
                downloaded_paths[output_parameter.name] = saved_path
                feedback.pushInfo(
                    self.tr("Saved output '{name}' to {path}").format(
                        name=output_parameter.name,
                        path=str(saved_path),
                    )
                )
                continue

            processing_results[output_parameter.name] = task_result.value

        return processing_results, downloaded_paths

    def _is_file_result(
        self,
        task_result: TaskResult,
        output_parameter: ToolOutputParameter,
    ) -> bool:
        del task_result
        return output_parameter.parameter_type == OutputParameterType.FILE

    def _download_result_file(
        self,
        task_id: str,
        task_result: TaskResult,
        output_parameter: ToolOutputParameter,
        parameters: Dict[str, Any],
        context: QgsProcessingContext,
    ) -> Path:
        destination_path = self._result_destination_path(
            task_id,
            task_result,
            output_parameter,
            parameters,
            context,
        )
        return self._api_client.download(task_result.value, destination_path)

    def _result_destination_path(
        self,
        task_id: str,
        task_result: TaskResult,
        output_parameter: ToolOutputParameter,
        parameters: Dict[str, Any],
        context: QgsProcessingContext,
    ) -> Path:
        if self._output_destination_resolver is not None:
            destination_path = self._output_destination_resolver(
                output_parameter,
                parameters,
                context,
            )
            if destination_path is not None:
                return self._normalized_destination_path(
                    destination_path,
                    task_result,
                    output_parameter,
                )

        temporary_directory = self._temporary_download_directory(task_id)
        result_filename = self._preferred_result_filename(
            task_result,
            output_parameter,
        )
        if result_filename is not None:
            return temporary_directory / result_filename

        return temporary_directory

    def _normalized_destination_path(
        self,
        destination_path: Path,
        task_result: TaskResult,
        output_parameter: ToolOutputParameter,
    ) -> Path:
        if destination_path.suffix.lower() not in ("", ".file"):
            return destination_path

        result_filename = self._preferred_result_filename(
            task_result,
            output_parameter,
        )
        if result_filename is None:
            return destination_path

        return destination_path.with_name(result_filename)

    def _preferred_result_filename(
        self,
        task_result: TaskResult,
        output_parameter: ToolOutputParameter,
    ) -> Optional[str]:
        raw_name = task_result.name.strip()
        if not raw_name:
            return None

        candidate_name = Path(raw_name).name
        candidate_suffix = Path(candidate_name).suffix.lower()
        if (
            candidate_name != output_parameter.name
            and candidate_suffix not in ("", ".file")
        ):
            return candidate_name

        inferred_suffix = self._preferred_result_suffix(task_result)
        if inferred_suffix is None and self._output_alias_implies_zip(
            output_parameter
        ):
            inferred_suffix = ".zip"

        if inferred_suffix is None:
            return None

        return f"{output_parameter.name}{inferred_suffix}"

    def _preferred_result_suffix(
        self,
        task_result: TaskResult,
    ) -> Optional[str]:
        result_value_path = Path(urlsplit(task_result.value).path)
        result_suffix = result_value_path.suffix.lower()
        if result_suffix in ("", ".file"):
            return None

        return result_suffix

    def _output_alias_implies_zip(
        self,
        output_parameter: ToolOutputParameter,
    ) -> bool:
        alias = output_parameter.alias
        if alias is None:
            return False

        return _ZIP_ALIAS_PATTERN.search(alias) is not None

    def _temporary_download_directory(self, task_id: str) -> Path:
        if self._temporary_results_directory is not None:
            return self._temporary_results_directory

        self._temporary_results_directory = Path(
            mkdtemp(prefix=f"nextgis_toolbox_{task_id}_")
        )
        return self._temporary_results_directory

    def _add_downloaded_outputs_to_project(
        self,
        downloaded_paths: Dict[str, Path],
    ) -> _OutputImportSummary:
        added_layer_count = 0
        skipped_outputs: List[Path] = []

        for output_name, output_path in downloaded_paths.items():
            layers = self._load_output_layers(output_name, output_path)
            if len(layers) == 0:
                skipped_outputs.append(output_path)
                continue

            for layer in layers:
                QgsProject.instance().addMapLayer(layer)
                added_layer_count += 1

        return _OutputImportSummary(
            added_layer_count=added_layer_count,
            skipped_paths=tuple(skipped_outputs),
        )

    def _load_output_layer(
        self,
        output_name: str,
        output_path: Path,
    ) -> Optional[QgsMapLayer]:
        layers = self._load_output_layers(output_name, output_path)
        if len(layers) == 0:
            return None

        return layers[0]

    def _load_output_layers(
        self,
        output_name: str,
        output_path: Path,
    ) -> List[QgsMapLayer]:
        loaded_layers: List[QgsMapLayer] = []
        seen_sources = set()

        for layer_candidate in self._layer_load_candidates(
            output_name,
            output_path,
        ):
            if layer_candidate.source in seen_sources:
                continue

            seen_sources.add(layer_candidate.source)
            layer = self._load_output_layer_from_source(
                layer_candidate.source,
                layer_candidate.name,
            )
            if layer is not None:
                loaded_layers.append(layer)

        return loaded_layers

    def _layer_load_candidates(
        self,
        output_name: str,
        output_path: Path,
    ) -> List[_LayerLoadCandidate]:
        layer_name = output_name or output_path.stem
        direct_candidates = self._query_layer_candidates(
            str(output_path),
            layer_name,
        )
        if len(direct_candidates) > 0:
            return direct_candidates

        if output_path.suffix.lower() != ".zip":
            return [_LayerLoadCandidate(str(output_path), layer_name)]

        archive_candidates: List[_LayerLoadCandidate] = []
        archive_root_source = f"/vsizip/{output_path}"
        for archived_source in self._archived_dataset_sources(output_path):
            archived_layer_candidates = self._query_layer_candidates(
                archived_source,
                layer_name,
            )
            if len(archived_layer_candidates) > 0:
                archive_candidates.extend(archived_layer_candidates)
                continue

            if archived_source == archive_root_source:
                continue

            archive_candidates.append(
                _LayerLoadCandidate(
                    archived_source,
                    Path(archived_source).stem or layer_name,
                )
            )

        if len(archive_candidates) > 0:
            return archive_candidates

        return [_LayerLoadCandidate(str(output_path), layer_name)]

    def _load_output_layer_from_source(
        self,
        layer_source: str,
        layer_name: str,
    ) -> Optional[QgsMapLayer]:
        vector_layer = QgsVectorLayer(layer_source, layer_name, "ogr")
        if vector_layer.isValid():
            return vector_layer

        raster_layer = QgsRasterLayer(layer_source, layer_name)
        if raster_layer.isValid():
            return raster_layer

        return None

    def _query_layer_candidates(
        self,
        layer_source: str,
        default_name: str,
    ) -> List[_LayerLoadCandidate]:
        try:
            sublayer_details = QgsProviderRegistry.instance().querySublayers(
                layer_source
            )
        except Exception as error:
            logger.debug(
                "Failed to query sublayers for '%s': %s",
                layer_source,
                error,
            )
            return []

        layer_candidates: List[_LayerLoadCandidate] = []
        for sublayer_detail in sublayer_details:
            sublayer_uri = sublayer_detail.uri()
            if not sublayer_uri:
                continue

            layer_candidates.append(
                _LayerLoadCandidate(
                    sublayer_uri,
                    self._layer_candidate_name(
                        sublayer_uri,
                        sublayer_detail.name(),
                        default_name,
                    ),
                )
            )

        return layer_candidates

    def _layer_candidate_name(
        self,
        sublayer_uri: str,
        detail_name: str,
        default_name: str,
    ) -> str:
        layer_name_marker = "|layername="
        if layer_name_marker in sublayer_uri:
            return sublayer_uri.rsplit(layer_name_marker, 1)[1]

        if detail_name:
            detail_path = Path(detail_name)
            if detail_path.suffix:
                return detail_path.stem

            return detail_name

        return default_name

    def _archived_dataset_sources(self, output_path: Path) -> List[str]:
        archived_sources = [f"/vsizip/{output_path}"]

        try:
            with ZipFile(output_path) as archive:
                for archive_member in archive.infolist():
                    if archive_member.is_dir():
                        continue

                    member_name = archive_member.filename
                    if not self._is_supported_archive_member(member_name):
                        continue

                    archived_sources.append(
                        f"/vsizip/{output_path}/{member_name}"
                    )
        except (BadZipFile, OSError) as error:
            logger.warning(
                "Failed to inspect archive output '%s': %s",
                output_path,
                error,
            )

        return archived_sources

    def _is_supported_archive_member(self, member_name: str) -> bool:
        member_suffix = Path(member_name).suffix.lower()
        return member_suffix in (
            _ARCHIVED_VECTOR_EXTENSIONS + _ARCHIVED_RASTER_EXTENSIONS
        )

    def _show_completion_message(
        self,
        downloaded_paths: Dict[str, Path],
        output_import_summary: _OutputImportSummary,
        feedback: QgsProcessingFeedback,
    ) -> None:
        message = self._completion_message(
            downloaded_paths,
            output_import_summary,
        )
        level = (
            Qgis.MessageLevel.Warning
            if output_import_summary.skipped_paths
            else Qgis.MessageLevel.Success
        )

        if output_import_summary.skipped_paths:
            feedback.pushInfo(message)

        notifier = self._message_notifier()
        if notifier is None:
            return

        notifier.display_message(
            message,
            duration=0,
            level=level,
            **self._success_message_widget_kwargs(downloaded_paths),
        )

    def _completion_message(
        self,
        downloaded_paths: Dict[str, Path],
        output_import_summary: _OutputImportSummary,
    ) -> str:
        message_parts = [self.tr("Task completed successfully.")]
        if downloaded_paths:
            message_parts.append(
                self.tr("Downloaded {count} output file(s).").format(
                    count=len(downloaded_paths),
                )
            )
        if output_import_summary.added_layer_count > 0:
            message_parts.append(
                self.tr("Added {count} layer(s) to the project.").format(
                    count=output_import_summary.added_layer_count,
                )
            )

        if not output_import_summary.skipped_paths:
            return " ".join(message_parts)

        warning_message = self.tr(
            "Some output files were not added to the project because they are not recognized as geodata:\n{paths}"
        ).format(
            paths="\n".join(
                str(path) for path in output_import_summary.skipped_paths
            )
        )
        return " ".join(message_parts) + "\n" + warning_message

    def _show_warning_message(
        self,
        message: str,
        feedback: QgsProcessingFeedback,
    ) -> None:
        feedback.pushInfo(message)

        notifier = self._message_notifier()
        if notifier is None:
            return

        notifier.display_message(
            message,
            duration=0,
            level=Qgis.MessageLevel.Warning,
        )

    def _message_notifier(self) -> Optional[NotifierInterface]:
        if self._notifier is not None:
            return self._notifier

        plugin = self._plugin_interface()
        if plugin is None or plugin.mode != plugin.Mode.GUI:
            return None

        return plugin.notifier

    def _plugin_interface(self) -> Optional[NextgisToolboxInterface]:
        try:
            return NextgisToolboxInterface.instance()
        except ToolboxError:
            return None

    def _saved_output_text(self, name: str, path: Path) -> str:
        return self.tr("{name}: {path}").format(
            name=name,
            path=str(path),
        )

    def _saved_output_html(self, name: str, path: Path) -> str:
        return self.tr("{name}: <a href='{url}'>{path}</a>").format(
            name=html.escape(name),
            url=html.escape(
                QUrl.fromLocalFile(str(path)).toString(),
                quote=True,
            ),
            path=html.escape(str(path)),
        )

    def _success_message_widgets(
        self,
        downloaded_paths: Dict[str, Path],
    ) -> Optional[List[QWidget]]:
        if not downloaded_paths:
            return None

        paths = list(downloaded_paths.values())
        reveal_button = QPushButton(
            self.tr("Show file") if len(paths) == 1 else self.tr("Show folder")
        )
        reveal_button.clicked.connect(
            lambda checked=False, current_paths=paths: self._reveal_outputs(
                current_paths
            )
        )

        copy_button = QPushButton(
            self.tr("Copy path") if len(paths) == 1 else self.tr("Copy paths")
        )
        copy_button.clicked.connect(
            lambda checked=False, current_paths=paths: self._copy_output_paths(
                current_paths
            )
        )

        return [reveal_button, copy_button]

    def _success_message_widget_kwargs(
        self,
        downloaded_paths: Dict[str, Path],
    ) -> Dict[str, Any]:
        if not downloaded_paths:
            return {}

        application = QCoreApplication.instance()
        if (
            application is None
            or QThread.currentThread() == application.thread()
        ):
            return {"widgets": self._success_message_widgets(downloaded_paths)}

        return {
            "widget_factories": self._success_message_widget_factories(
                downloaded_paths
            )
        }

    def _success_message_widget_factories(
        self,
        downloaded_paths: Dict[str, Path],
    ) -> List[Callable[[], QWidget]]:
        if not downloaded_paths:
            return []

        paths = tuple(downloaded_paths.values())
        return [
            lambda current_paths=paths: self._create_reveal_button(
                current_paths
            ),
            lambda current_paths=paths: self._create_copy_button(
                current_paths
            ),
        ]

    def _create_reveal_button(self, paths: Sequence[Path]) -> QPushButton:
        reveal_button = QPushButton(
            self.tr("Show file") if len(paths) == 1 else self.tr("Show folder")
        )
        reveal_button.clicked.connect(
            lambda checked=False, current_paths=paths: self._reveal_outputs(
                current_paths
            )
        )
        return reveal_button

    def _create_copy_button(self, paths: Sequence[Path]) -> QPushButton:
        copy_button = QPushButton(
            self.tr("Copy path") if len(paths) == 1 else self.tr("Copy paths")
        )
        copy_button.clicked.connect(
            lambda checked=False, current_paths=paths: self._copy_output_paths(
                current_paths
            )
        )
        return copy_button

    def _reveal_outputs(self, paths: Sequence[Path]) -> None:
        if not paths:
            return

        if len(paths) == 1:
            reveal_in_file_manager(paths[0])
            return

        reveal_in_file_manager(paths[0].parent)

    def _copy_output_paths(self, paths: Sequence[Path]) -> None:
        if not paths:
            return

        clipboard_text = "\n".join(str(path) for path in paths)
        set_clipboard_data(
            "text/plain",
            clipboard_text.encode("utf-8"),
            clipboard_text,
        )

    def _raise_task_failed(
        self, task_id: str, task: ToolboxTaskInformation
    ) -> None:
        """Raise a specialized exception for a failed backend task."""
        error_message = task.error or self.tr("No error details provided.")
        diagnostic_details = (
            f"task_id={task_id}; status={task.status.value}; "
            f"error={error_message}"
        )
        logger.warning(
            f"Tool '{self._tool.name}' failed. {diagnostic_details}"
        )
        wrapped_error = ToolboxTaskFailedError(
            log_message=(
                f"Tool '{self._tool.name}' failed. {diagnostic_details}"
            ),
        )
        wrapped_error.add_note(f"Technical details: {diagnostic_details}")
        raise wrapped_error

    def _raise_if_unknown_status_exceeded(
        self,
        snapshot: TaskExecutionSnapshot,
        consecutive_unknown_polls: int,
        unknown_started_at: float,
    ) -> None:
        """Raise when UNKNOWN status exceeds the grace period."""
        unknown_elapsed = self._monotonic() - unknown_started_at
        if (
            consecutive_unknown_polls <= self._unknown_status_poll_limit
            and unknown_elapsed <= self._unknown_status_grace_seconds
        ):
            return

        wrapped_error = ToolboxTaskExecutionError(
            log_message=(
                f"Task '{snapshot.task_id}' remained in UNKNOWN status "
                "beyond the allowed grace period"
            ),
        )
        wrapped_error.add_note(
            "Technical details: "
            f"polls={consecutive_unknown_polls}; "
            f"elapsed={unknown_elapsed:.3f}s"
        )
        raise wrapped_error

    def _raise_if_wait_timeout_exceeded(
        self,
        task_id: str,
        started_at: float,
    ) -> None:
        """Raise when client-side waiting exceeds the configured timeout."""
        if self._wait_timeout_seconds is None:
            return

        elapsed_seconds = self._monotonic() - started_at
        if elapsed_seconds <= self._wait_timeout_seconds:
            return

        wrapped_error = ToolboxTaskTimeoutError(
            log_message=(
                f"Task '{task_id}' exceeded client-side wait timeout"
            ),
        )
        wrapped_error.add_note(
            "Technical details: "
            f"elapsed={elapsed_seconds:.3f}s; "
            f"timeout={self._wait_timeout_seconds:.3f}s"
        )
        raise wrapped_error

    def _cancel_if_requested(
        self,
        feedback: QgsProcessingFeedback,
        *,
        task_id: Optional[str],
    ) -> bool:
        """Handle user cancellation and report it to the feedback."""
        if not feedback.isCanceled():
            return False

        self._set_execution_state(
            feedback,
            TaskExecutionState.CANCELED_BY_USER,
            backend_status=TaskStatus.UNKNOWN,
        )

        if task_id is None:
            feedback.pushInfo(self.tr("Execution was canceled."))
            logger.warning(
                f"Tool '{self._tool.name}' execution was canceled by user"
            )
            return True

        feedback.pushInfo(
            self.tr(
                "Execution was canceled. "
                "The task continues on the server side."
            )
        )
        logger.warning(
            f"Tool '{self._tool.name}' execution was canceled by user; "
            f"task_id='{task_id}'"
        )
        return True

    def _is_server_file_reference(self, value: Any) -> bool:
        """Return whether the value already looks like a server file."""
        if isinstance(value, str):
            return self._looks_like_remote_file(value)

        if not isinstance(value, dict):
            return False

        url = value.get("url") or value.get("href")
        if isinstance(url, str) and url.strip():
            return True

        local = value.get("local")
        if isinstance(local, dict):
            uuid = local.get("uuid")
            if isinstance(uuid, str) and uuid.strip():
                return True

        uuid = value.get("uuid")
        return isinstance(uuid, str) and bool(uuid.strip())

    def _looks_like_remote_file(self, value: str) -> bool:
        """Return whether a string looks like a remote file reference."""
        return value.strip().startswith(_REMOTE_FILE_PREFIXES)

    def tr(self, text: str) -> str:
        """Translate a user-facing string."""
        return QCoreApplication.translate(self.__class__.__name__, text)
