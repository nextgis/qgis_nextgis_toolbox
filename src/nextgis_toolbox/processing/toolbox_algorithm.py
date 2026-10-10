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

from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Optional,
    cast,
)

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingContext,
    QgsProcessingFeedback,
)
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtGui import QIcon

from nextgis_toolbox.api.client import ToolboxApiClient
from nextgis_toolbox.core.utils import PluginRuntimeProfiler
from nextgis_toolbox.nextgis_toolbox_interface import (
    NextgisToolboxInterface,
)
from nextgis_toolbox.notifier.notifier_interface import NotifierInterface
from nextgis_toolbox.processing.parameters import (
    ADD_RESULTS_TO_PROJECT_PARAMETER_NAME,
    EMAIL_NOTIFICATION_PARAMETER_NAME,
    ProcessingParameterRegistry,
)
from nextgis_toolbox.processing.parameters.controls import (
    ProcessingControlParameterFactory,
)
from nextgis_toolbox.processing.parameters.resolvers import (
    AlgorithmOutputDestinationResolver,
    AlgorithmParameterResolver,
)
from nextgis_toolbox.processing.tool_content_formatter import (
    FormattedToolHelp,
    ToolContentFormatter,
)
from nextgis_toolbox.processing.toolbox_task_executor import (
    ToolboxTaskExecutor,
)
from nextgis_toolbox.tasks.tasks_interface import (
    TasksInterface,
)
from nextgis_toolbox.tools.models import (
    OutputParameterType,
    ToolboxTool,
)
from nextgis_toolbox.ui.icon import plugin_icon

if TYPE_CHECKING:
    from nextgis_toolbox.processing.nextgis_toolbox_processing_provider import (
        NextgisToolboxProcessingProvider,
    )


class ToolboxAlgorithm(QgsProcessingAlgorithm):
    """
    Processing algorithm for a single NextGIS Toolbox tool.
    """

    _tool: ToolboxTool
    _tasks_manager: TasksInterface
    _parameter_registry: ProcessingParameterRegistry
    _notifier_resolver: Optional[Callable[[], Optional[NotifierInterface]]]

    def __init__(
        self,
        tool: ToolboxTool,
        tasks_manager: TasksInterface,
        parameter_registry: ProcessingParameterRegistry,
    ) -> None:
        """
        Initialize processing algorithm.

        :param tool: Toolbox tool descriptor.
        :param tasks_manager: Tasks feature interface.
        """
        super().__init__()

        self._tool = tool
        self._tasks_manager = tasks_manager
        self._parameter_registry = parameter_registry
        self._notifier_resolver = None
        self._help_content_cache: Dict[bool, FormattedToolHelp] = {}

    def icon(self) -> QIcon:
        return plugin_icon("algorithm.svg")

    def createInstance(self) -> "ToolboxAlgorithm":
        """
        Create new algorithm instance.

        :returns: New algorithm instance.
        """
        clone = type(self)(
            tool=self._tool,
            tasks_manager=self._tasks_manager,
            parameter_registry=self._parameter_registry,
        )
        clone._notifier_resolver = self._notifier_resolver

        provider = cast("NextgisToolboxProcessingProvider", self.provider())
        if provider is not None:
            provider.algorithm_instance_created.emit(clone)

        return clone

    def initAlgorithm(
        self,
        configuration: Optional[Dict[Optional[str], Any]] = None,
    ) -> None:
        """
        Declare algorithm parameters and outputs.

        :param configuration: Optional provider configuration dict
            (unused, required by base class API).
        """
        for input_parameter in self.tool.inputs:
            representation = (
                self._parameter_registry.create_input_representation(
                    input_parameter,
                    tool_inputs=self.tool.inputs,
                )
            )
            self._add_parameters(representation.parameters)

        has_file_outputs = False
        for output_param in self._tool.outputs:
            representation = (
                self._parameter_registry.create_output_representation(
                    output_param
                )
            )
            self._add_outputs(representation.outputs)
            self._add_parameters(representation.parameters)

            if output_param.parameter_type == OutputParameterType.FILE:
                has_file_outputs = True

        control_parameter_factory = ProcessingControlParameterFactory()
        if has_file_outputs:
            self.addParameter(
                control_parameter_factory.create_add_to_project()
            )

        self.addParameter(
            control_parameter_factory.create_email_notification()
        )

    def processAlgorithm(
        self,
        parameters: Dict[Optional[str], Any],
        context: QgsProcessingContext,
        feedback: Optional[QgsProcessingFeedback],
    ) -> Dict[str, Any]:
        """
        Execute processing algorithm.

        :param parameters: Processing parameters.
        :param context: Processing context.
        :param feedback: Processing feedback.

        :returns: Processing result.
        """
        if feedback is None:
            feedback = QgsProcessingFeedback()

        result = {}

        with PluginRuntimeProfiler(f"executing tool '{self._tool.alias}'"):
            emailing = self.parameterAsBool(
                parameters,
                EMAIL_NOTIFICATION_PARAMETER_NAME,
                context,
            )
            add_to_project = False
            if self._has_file_outputs():
                add_to_project = self.parameterAsBool(
                    parameters,
                    ADD_RESULTS_TO_PROJECT_PARAMETER_NAME,
                    context,
                )

            tasks_api = self._tasks_manager.api()
            executor = ToolboxTaskExecutor(
                api_client=tasks_api.api_client,
                task_submitter=tasks_api.submit_task,
                task_information_resolver=self._tasks_manager.task_information,
                task_results_url_resolver=(
                    lambda task_id: tasks_api.task_results_url(
                        task_id
                    ).toString()
                ),
                tool=self._tool,
                parameter_resolver=AlgorithmParameterResolver(
                    self,
                    self._parameter_registry,
                ),
                notifier=self.notifier,
                output_destination_resolver=AlgorithmOutputDestinationResolver(
                    self
                ),
            )

            result = executor.execute(
                parameters=cast(Dict[str, Any], parameters),
                context=context,
                feedback=feedback,
                emailing=emailing,
                add_to_project=add_to_project,
            )

        return result

    @property
    def tool(self) -> ToolboxTool:
        """Return the toolbox tool associated with this algorithm."""
        return self._tool

    @property
    def parameter_registry(self) -> ProcessingParameterRegistry:
        return self._parameter_registry

    @property
    def notifier(self) -> Optional[NotifierInterface]:
        if self._notifier_resolver is None:
            return None

        return self._notifier_resolver()

    def set_notifier_resolver(
        self,
        notifier_resolver: Optional[Callable[[], Optional[NotifierInterface]]],
    ) -> None:
        self._notifier_resolver = notifier_resolver

    def name(self) -> str:
        """
        Return internal algorithm identifier.

        :returns: Algorithm identifier.
        """
        return self._tool.name

    def displayName(self) -> str:
        """
        Return visible algorithm name.

        :returns: Display name.
        """
        return self._tool.alias

    def shortDescription(self) -> str:
        """
        Return algorithm short description.

        :returns: Short description.
        """
        return ToolContentFormatter().format_description(self._tool)

    def shortHelpString(self) -> str:
        """
        Return algorithm help text.

        :returns: Help text.
        """
        return self.help_content().render()

    def helpUrl(self) -> str:
        """Return URL to the tool documentation.

        :returns: Documentation URL based on the current locale.
        """
        return self._tool.help_url()

    def tags(self) -> List[str]:
        return [tag.alias for tag in self._tool.tags]

    def tool_web_url(self) -> str:
        """Return URL to the toolbox tool page."""
        return self._tool.web_url(self._endpoint())

    def api_client(self) -> ToolboxApiClient:
        return self._tasks_manager.api().api_client

    def help_content(
        self,
        *,
        defer_images: Optional[bool] = None,
    ) -> FormattedToolHelp:
        should_defer_images = defer_images
        if should_defer_images is None:
            should_defer_images = self._should_defer_help_images()

        cached_help = self._help_content_cache.get(should_defer_images)
        if cached_help is not None:
            return cached_help

        help_content = ToolContentFormatter(
            self._endpoint(),
            api_client=self.api_client(),
        ).prepare_help(
            self._tool,
            defer_images=should_defer_images,
            embed_images=False,
        )
        self._help_content_cache[should_defer_images] = help_content
        return help_content

    def rendered_help_html(
        self,
        image_sources: Optional[Dict[str, str]] = None,
        *,
        defer_images: bool = True,
    ) -> str:
        return self.help_content(
            defer_images=defer_images,
        ).render_dialog_html(
            self.displayName(),
            image_sources,
        )

    def _endpoint(self) -> str:
        return self._tasks_manager.api().api_client.endpoint

    def _has_file_outputs(self) -> bool:
        return any(
            output_parameter.parameter_type == OutputParameterType.FILE
            for output_parameter in self._tool.outputs
        )

    def _should_defer_help_images(self) -> bool:
        plugin = NextgisToolboxInterface.instance()
        return plugin.mode == plugin.Mode.GUI

    def tr(self, text: str) -> str:
        """
        Translate a string via Qt's translation system.

        :param text: Source string.

        :returns: Translated string.
        """
        return QCoreApplication.translate(self.__class__.__name__, text)

    def _add_parameters(self, parameters: Iterable[Any]) -> None:
        for parameter in parameters:
            self.addParameter(parameter)

    def _add_outputs(self, outputs: Iterable[Any]) -> None:
        for output in outputs:
            self.addOutput(output)
