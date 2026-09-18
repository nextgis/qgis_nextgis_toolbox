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

import configparser
import sys
from enum import Enum
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Optional,
    Type,
    TypeVar,
    cast,
)

from osgeo import gdal
from qgis import utils
from qgis.core import Qgis, QgsApplication, QgsTaskManager
from qgis.gui import QgisInterface, QgsMessageBar
from qgis.PyQt.QtCore import (
    QT_VERSION_STR,
    QObject,
    QSysInfo,
    QTranslator,
    QUrl,
    pyqtSignal,
    pyqtSlot,
)
from qgis.PyQt.QtGui import QDesktopServices, QIcon

from nextgis_toolbox.core.constants import (
    COMPANY_NAME,
    DEFAULT_TRANSLATION,
    PACKAGE_NAME,
    PLUGIN_NAME,
    UTM_TERM,
)
from nextgis_toolbox.core.exceptions import ToolboxError
from nextgis_toolbox.core.logging import logger, unload_logger
from nextgis_toolbox.core.types import Unset, Unsettable, UnsetType
from nextgis_toolbox.core.utils import (
    PluginRuntimeProfiler,
    assert_not_none,
    plugin_path,
    qgis_locale,
    real_plugin_path,
    supported_translations,
    utm_tags,
)
from nextgis_toolbox.notifier.cli_notifier import CliNotifier
from nextgis_toolbox.notifier.message_bar_notifier import MessageBarNotifier
from nextgis_toolbox.shared.qobject_metaclass import QObjectMetaClass
from nextgis_toolbox.ui.icon import plugin_icon

if TYPE_CHECKING:
    from nextgis_toolbox.api.client import ToolboxApiClient
    from nextgis_toolbox.notifier.notifier_interface import (
        NotifierInterface,
    )
    from nextgis_toolbox.processing.nextgis_toolbox_processing_provider import (
        NextgisToolboxProcessingProvider,
    )
    from nextgis_toolbox.tasks.tasks_interface import (
        TasksInterface,
    )
    from nextgis_toolbox.tools.tools_interface import (
        ToolsInterface,
    )


class NextgisToolboxInterface(QObject, metaclass=QObjectMetaClass):
    """Interface for the NextGIS Toolbox.

    This abstract base class provides singleton access to the plugin
    instance, exposes plugin metadata, version, and path, and defines
    abstract properties and methods that must be implemented by concrete
    subclasses.
    """

    class Mode(Enum):
        """Enum representing the plugin mode."""

        LOADING = "loading"
        GUI = "gui"
        PROCESSING = "processing"
        ERROR = "error"
        UNLOADED = "unloaded"

    settings_changed = pyqtSignal()
    _instance: Optional["NextgisToolboxInterface"] = None

    def __init__(self, iface: QgisInterface) -> None:
        super().__init__(iface)

        NextgisToolboxInterface._instance = self

        self._mode = self.Mode.LOADING
        self._is_gui_loaded = False
        self._is_processing_loaded = False
        self._notifier = None  # type: Optional[NotifierInterface]
        self._metadata = None
        self._translators = list()

    @classmethod
    def instance(cls) -> "NextgisToolboxInterface":
        """Return the singleton instance of the NextGIS Toolbox.

        :returns: The NextgisToolboxInterface plugin instance.

        :raises AssertionError: If the plugin has not been created yet.
        """
        return assert_not_none(
            cls._instance,
            "Using a plugin before it was created",
        )

    @property
    def qgis_iface(self) -> QgisInterface:
        """Return the QGIS interface instance.

        :returns: QGIS interface instance.
        """
        return cast(QgisInterface, self.parent())

    @property
    def metadata(self) -> "PluginMetadata":
        """Return the parsed metadata for the plugin.

        :returns: Parsed metadata as a PluginMetadata object.
        """
        if self._metadata is not None:
            return self._metadata

        raw_metadata = utils.plugins_metadata_parser.get(PACKAGE_NAME)
        if raw_metadata is None:
            raise ToolboxError("Failed to load plugin metadata")

        self._metadata = PluginMetadata(raw_metadata)
        return self._metadata

    @property
    def path(self) -> "Path":
        """Return the plugin path.

        :returns: Path to the plugin directory.
        """
        return plugin_path()

    @property
    def mode(self) -> Mode:
        """Return the plugin mode.

        :returns: The plugin mode (GUI or PROCESSING).
        """
        return self._mode

    @property
    def notifier(self) -> "NotifierInterface":
        """Return the notifier for displaying messages to the user.

        :returns: Notifier interface instance.
        """
        if self._notifier is None:
            raise ToolboxError("Using notifier before it was initialized")
        return self._notifier

    @property
    def tools_manager(self) -> "ToolsInterface":
        """Return the tools feature manager.

        :returns: Tools feature interface instance.

        :raises NextgisToolboxError: If a plugin implementation does not
            provide the tools feature.
        """
        raise ToolboxError("Plugin does not implement tools manager access")

    @property
    def tasks_manager(self) -> "TasksInterface":
        """Return the tasks feature manager.

        :returns: Tasks feature interface instance.

        :raises NextgisToolboxError: If a plugin implementation does not
            provide the tasks feature.
        """
        raise ToolboxError("Plugin does not implement tasks manager access")

    @property
    def processing_provider(self) -> "NextgisToolboxProcessingProvider":
        """Return the Processing provider instance.

        :returns: Processing provider instance.

        :raises NextgisToolboxError: If a plugin implementation does not
            provide the processing provider.
        """
        raise ToolboxError(
            "Plugin does not implement Processing provider access"
        )

    @property
    def api_client(self) -> "ToolboxApiClient":
        raise ToolboxError("Plugin does not implement API client access")

    @property
    def qgis_tasks_manager(self) -> QgsTaskManager:
        raise ToolboxError(
            "Plugin does not implement QGIS tasks manager access"
        )

    @pyqtSlot()
    def open_about_dialog(self) -> None:
        """Open the plugin about dialog."""
        raise ToolboxError("Plugin does not implement about dialog")

    @pyqtSlot()
    def open_settings(self) -> None:
        """Open the plugin settings dialog."""
        self.qgis_iface.showOptionsDialog(
            self.qgis_iface.mainWindow(), PLUGIN_NAME
        )

    @pyqtSlot()
    def report_problem(self) -> None:
        """Open the problem reporting dialog."""
        tracker_url = self.metadata.tracker
        if self.mode == self.Mode.PROCESSING:
            self.notifier.display_message(
                self.tr(
                    "Please let us know about the issue: {tracker_url}"
                ).format(tracker_url=tracker_url),
                level=Qgis.MessageLevel.Warning,
            )
            return

        if self.metadata.is_public:
            QDesktopServices.openUrl(QUrl(tracker_url))
        elif "mailto:" in tracker_url:
            QDesktopServices.openUrl(QUrl(tracker_url))
        else:
            utm = utm_tags("error")
            QDesktopServices.openUrl(QUrl(f"{tracker_url}/?{utm}"))

    @PluginRuntimeProfiler.wrap("load plugin in GUI mode")
    def initGui(self) -> None:
        """Initialize the GUI components and load necessary resources."""
        self._mode = self.Mode.GUI
        self._notifier = MessageBarNotifier(
            cast(QgsMessageBar, self.qgis_iface.messageBar())
        )

        try:
            self._log_versions()
            self._load_translations()

            if self.metadata.has_processing_provider:
                self._init_processing()

            self._is_gui_loaded = self._load_ui()
            if not self._is_gui_loaded:
                raise ToolboxError("Failed to load GUI components")

        except Exception as error:
            logger.error("An error occurred while initializing the GUI")
            self._process_error(error)
            return

    @PluginRuntimeProfiler.wrap("load plugin in processing mode")
    def initProcessing(self) -> None:
        """Initialize the processing provider and algorithms."""
        self._mode = self.Mode.PROCESSING
        self._notifier = CliNotifier(self)

        try:
            self._log_versions()
            self._init_processing()

        except Exception as error:
            logger.error("An error occurred while initializing processing")
            self._process_error(error)
            return

    def unload(self) -> None:
        """Unload the plugin and perform cleanup operations."""
        try:
            if self._is_gui_loaded:
                self._unload_ui()

            if self._is_processing_loaded:
                self._unload_processing()

            if self._translators:
                self._unload_translations()

            self._unload_notifier()

        except Exception:
            logger.warning(
                "An error occurred while unloading the plugin, some resources"
                " may not be cleaned up properly"
            )

        finally:
            if NextgisToolboxInterface._instance is self:
                NextgisToolboxInterface._instance = None

        logger.debug("✓ Plugin unloaded")

        unload_logger()

        self._mode = self.Mode.UNLOADED

    def _init_processing(self) -> None:
        """Initialize the processing provider and algorithms."""
        if self.mode == self.Mode.ERROR:
            logger.debug(
                "Plugin is in error mode, skipping processing provider initialization"
            )
            return

        self._is_processing_loaded = self._load_processing()
        if not self._is_processing_loaded:
            raise ToolboxError("Failed to load processing provider")

    def _load_ui(self) -> bool:
        """Load the plugin resources and initialize components.

        This method must be implemented by subclasses.
        """
        if self._mode == self.Mode.ERROR:
            logger.debug("Plugin is in error mode, skipping UI loading")
            return False

        raise ToolboxError(
            "Plugin has UI components but they are not implemented"
        )

    def _unload_ui(self) -> None:
        """Unload the plugin resources and clean up components.

        This method must be implemented by subclasses.
        """
        if self._mode == self.Mode.ERROR:
            logger.debug("Plugin is in error mode, skipping UI unloading")
            return

        raise ToolboxError(
            "Plugin has UI components but they are not implemented"
        )

    def _load_processing(self) -> bool:
        """Load the processing provider and algorithms.

        This method must be implemented by subclasses.
        """
        if self.mode == self.Mode.ERROR:
            logger.debug(
                "Plugin is in error mode, skipping processing provider loading"
            )
            return True

        raise ToolboxError(
            "Plugin has processing provider but it is not implemented"
        )

    def _unload_processing(self) -> None:
        """Unload the processing provider and algorithms.

        This method must be implemented by subclasses.
        """
        if self.mode == self.Mode.ERROR:
            logger.debug(
                "Plugin is in error mode, skipping processing provider unloading"
            )
            return

        raise ToolboxError(
            "Plugin has processing provider but it is not implemented"
        )

    def _add_translator(self, translator_path: Path) -> None:
        """Add a translator for the plugin.

        :param translator_path: Path to the translation file.
        """
        translator = QTranslator()
        is_loaded = translator.load(str(translator_path))
        if not is_loaded:
            logger.debug(f"Translator {translator_path} wasn't loaded")
            return

        is_installed = QgsApplication.installTranslator(translator)
        if not is_installed:
            logger.error(f"Translator {translator_path} wasn't installed")
            return

        # Should be kept in memory
        self._translators.append(translator)

    def _load_translations(self) -> None:
        """Load translation files for the plugin."""
        self._translators = list()
        locale = qgis_locale()
        if locale == DEFAULT_TRANSLATION:
            return

        translator_path = self.path / "i18n" / f"{PACKAGE_NAME}_{locale}.qm"
        self._add_translator(translator_path)

    def _unload_translations(self) -> None:
        """Remove all translators added by the plugin."""
        for translator in self._translators:
            QgsApplication.removeTranslator(translator)
        self._translators.clear()

    def _unload_notifier(self) -> None:
        """Unload the notifier component."""
        if self._notifier is None:
            return

        self._notifier.deleteLater()
        self._notifier = None

    def _log_versions(self) -> None:
        """Log versions of QGIS, Python, GDAL, and the plugin itself."""
        logger.debug("ⓘ Environment:")

        logger.debug(f"<b>ⓘ OS:</b> {QSysInfo().prettyProductName()}")
        logger.debug(f"<b>ⓘ Current locale:</b> {qgis_locale(adapt=False)}")
        logger.debug(f"<b>ⓘ Qt version:</b> {QT_VERSION_STR}")
        logger.debug(f"<b>ⓘ QGIS version:</b> {Qgis.version()}")
        logger.debug(f"<b>ⓘ Python version:</b> {sys.version}")
        logger.debug(f"<b>ⓘ GDAL version:</b> {gdal.__version__}")

        logger.debug(f"<b>ⓘ Plugin name:</b> {self.metadata.name}")
        logger.debug(f"<b>ⓘ Plugin version:</b> {self.metadata.version}")

        log_function = (
            logger.warning if self.metadata.is_experimental else logger.debug
        )
        log_function(
            f"<b>ⓘ Plugin experimental:</b> {self.metadata.is_experimental}"
        )
        log_function = (
            logger.warning if self.metadata.is_deprecated else logger.debug
        )
        log_function(
            f"<b>ⓘ Plugin deprecated:</b> {self.metadata.is_deprecated}"
        )

        logger.debug(
            f"<b>ⓘ Plugin path:</b> {self.path}"
            + (
                f" -> {real_plugin_path()}"
                if self.metadata.is_editable_installation
                else ""
            )
        )
        translations = supported_translations()
        logger.debug(
            "<b>ⓘ Supported translations:</b> " + ", ".join(translations)
        )
        current_translation = (
            qgis_locale() if self._translators else DEFAULT_TRANSLATION
        )
        logger.debug(f"<b>ⓘ Current translation:</b> {current_translation}")

    def _process_error(self, error: Exception) -> None:
        """Log an error with its traceback."""
        self._mode = self.Mode.ERROR
        logger.exception(
            "Unhandled plugin error",
            exc_info=error,
        )
        if self._notifier is not None:
            self._notifier.display_exception(error)


class NextgisToolboxPluginStub(NextgisToolboxInterface):
    """Stub implementation of plugin interface used to notify the user when the plugin failed to start."""

    def __init__(self, iface: QgisInterface) -> None:
        """Initialize the plugin stub."""
        super().__init__(iface)
        self._mode = self.Mode.ERROR
        logger.debug("<b>✓ Plugin stub created</b>")


T = TypeVar("T")


def _metadata_property(
    key: str,
    *,
    default: Unsettable[T] = Unset,
    default_factory: Optional[Callable[[], T]] = None,
    value_type: Type,
) -> property:
    """Create a typed metadata property."""

    def getter(self: "PluginMetadata") -> T:
        fallback = default
        if default_factory is not None:
            fallback = cast(T, default_factory())
        return self._value(key, default=fallback, value_type=value_type)

    return property(getter)


class PluginMetadata:
    """Class representing the plugin metadata.

    This class provides access to the plugin metadata fields defined in the
    metadata.txt file.
    """

    GENERAL_SECTION = "general"

    def __init__(self, metadata: configparser.ConfigParser) -> None:
        self._metadata = metadata

    name = _metadata_property("name", default=PLUGIN_NAME, value_type=str)
    author = _metadata_property("author", default=COMPANY_NAME, value_type=str)
    email = _metadata_property(
        "email", default="info@nextgis.com", value_type=str
    )
    homepage = _metadata_property(
        "homepage", default="https://nextgis.com", value_type=str
    )
    description = _metadata_property("description", default="", value_type=str)
    about = _metadata_property("about", default="", value_type=str)
    version = _metadata_property("version", default="0.0.0", value_type=str)
    is_experimental = _metadata_property(
        "experimental", default=False, value_type=bool
    )
    is_deprecated = _metadata_property(
        "deprecated", default=False, value_type=bool
    )
    tags = _metadata_property("tags", default_factory=list, value_type=list)
    has_processing_provider = _metadata_property(
        "hasProcessingProvider", default=False, value_type=bool
    )
    dependencies = _metadata_property(
        "plugin_dependencies", default_factory=list, value_type=list
    )
    utm_term = property(lambda self: UTM_TERM)

    @property
    def is_editable_installation(self) -> bool:
        """Return whether the plugin is installed in develop mode."""
        return plugin_path() != real_plugin_path()

    @property
    def is_public(self) -> bool:
        """Return whether the plugin is public."""
        return "github" in self.tracker

    @property
    def icon(self) -> QIcon:
        """Return the plugin icon."""
        if not self._metadata.has_option(self.GENERAL_SECTION, "icon"):
            logger.error("Plugin metadata is missing 'icon' field")
            return QIcon()

        icon = plugin_icon()
        if icon.isNull():
            logger.error("Failed to load plugin icon")
            return icon

        return icon

    def __getattr__(self, key: str) -> Any:
        try:
            return self._value(key)
        except KeyError as error:
            raise AttributeError(
                f"Metadata has no attribute '{key}'"
            ) from error

    def _value(
        self,
        key: str,
        *,
        default: Unsettable[T] = Unset,
        value_type: Unsettable[Type] = Unset,
    ) -> T:
        for key in (f"{key}[{qgis_locale()}]", key):
            value = self._extract_typed_value(
                key, default=Unset, value_type=value_type
            )
            if not isinstance(value, UnsetType):
                return value

        if isinstance(default, UnsetType):
            raise KeyError(
                f"Metadata key '{key}' not found and no default value provided"
            )

        return default

    def _extract_typed_value(
        self,
        key: str,
        *,
        default: Unsettable[T] = Unset,
        value_type: Unsettable[Type] = Unset,
    ) -> Unsettable[T]:
        if value_type is Unset or value_type is str:
            value = self._metadata.get(
                self.GENERAL_SECTION, key, fallback=Unset
            )

        elif value_type is bool:
            value = self._metadata.getboolean(
                self.GENERAL_SECTION, key, fallback=Unset
            )

        elif value_type is int:
            value = self._metadata.getint(
                self.GENERAL_SECTION, key, fallback=Unset
            )

        elif value_type is list:
            values_string = self._metadata.get(
                self.GENERAL_SECTION, key, fallback=""
            )
            if len(values_string) != 0:
                value = [
                    tag.strip()
                    for tag in values_string.split(",")
                    if tag.strip()
                ]
            else:
                value = Unset

        else:
            raise TypeError(f"Unsupported metadata value type: {value_type}")

        if not isinstance(value, UnsetType):
            return cast(T, value)

        return default
