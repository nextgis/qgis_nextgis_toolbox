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

from unittest.mock import Mock

import pytest
from qgis.core import QgsFeedback

from nextgis_toolbox.tasks.models import (
    TaskResult,
    TaskStatus,
    ToolboxTaskInformation,
)
from nextgis_toolbox.tasks.tasks_manager import TasksManager


def test_tasks_manager_submits_task_and_emits_signal(qgis_app) -> None:
    del qgis_app

    manager = TasksManager(Mock())
    repository = Mock()
    repository.submit_task.return_value = "task-1"
    manager._repository = repository
    captured_task_ids = []
    manager.task_created.connect(captured_task_ids.append)

    task_id = manager.submit_task(
        "hello",
        {"name": "value"},
        emailing=True,
    )

    assert task_id == "task-1"
    assert captured_task_ids == ["task-1"]
    repository.submit_task.assert_called_once_with(
        tool_name="hello",
        inputs={"name": "value"},
        emailing=True,
    )


@pytest.mark.parametrize("with_feedback", [False, True])
def test_tasks_manager_delegates_read_operations(
    qgis_app, with_feedback
) -> None:
    del qgis_app

    manager = TasksManager(Mock())
    repository = Mock()
    result = TaskResult(
        name="result",
        value="http://example.com/result.txt",
    )
    task = ToolboxTaskInformation(
        tool="hello",
        status=TaskStatus.SUCCESS,
        progress=100.0,
        error=None,
        results=[result],
        operation="hello",
    )
    repository.task_information.return_value = task
    manager._repository = repository
    feedback = QgsFeedback() if with_feedback else None

    assert manager.task_information("task-1", feedback=feedback) is task
    assert task.results == [result]

    repository.task_information.assert_called_once_with(
        "task-1", feedback=feedback
    )


def test_tasks_manager_lifecycle_preserves_api_access(qgis_app) -> None:
    del qgis_app

    api = Mock()
    manager = TasksManager(api)
    manager.load()
    assert manager.api() is api
    manager.unload()
    replacement = Mock()
    manager.set_api(replacement)
    assert manager.api() is replacement
