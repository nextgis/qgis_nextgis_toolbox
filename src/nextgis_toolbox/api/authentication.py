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

from abc import ABC, abstractmethod
from typing import Dict
from uuid import UUID

from qgis.PyQt.QtNetwork import QNetworkRequest

from nextgis_toolbox.settings.nextgis_toolbox_settings import (
    AuthenticationType,
)


class ToolboxAuthentication(ABC):
    """
    Manages NextGIS Toolbox authentication credentials.
    """

    TYPE = AuthenticationType.NONE

    @property
    @abstractmethod
    def headers(self) -> Dict[str, str]:
        """
        Get HTTP headers required for authenticated API requests.

        :returns: Dictionary of HTTP headers.
        """
        ...

    @abstractmethod
    def apply(self, request: QNetworkRequest) -> None:
        """
        Apply authentication to the given network request.

        :param request: Network request to apply authentication to.
        """
        ...


class ToolboxTokenAuthentication(ToolboxAuthentication):
    """Token-based authentication for NextGIS Toolbox API"""

    TYPE = AuthenticationType.TOKEN

    def __init__(self, token: str) -> None:
        """
        Initialize authentication instance.

        :param token: NextGIS Toolbox API token.
        """

        self._token: UUID = UUID(token)

    def __eq__(self, other: object) -> bool:
        """Compare token authentication instances by their token."""
        return (
            isinstance(other, ToolboxTokenAuthentication)
            and self._token == other._token
        )

    @property
    def token(self) -> str:
        """Return the configured API token as a string."""
        return str(self._token)

    @property
    def headers(self) -> Dict[str, str]:
        """
        Get HTTP headers required for authenticated API requests.

        :returns: Dictionary of HTTP headers.
        """

        return {
            "Authorization": f"Token {self._token}",
        }

    def apply(self, request: QNetworkRequest) -> None:
        """
        Apply authentication headers to the given network request.

        :param request: Network request to apply authentication to.
        """

        for key, value in self.headers.items():
            request.setRawHeader(key.encode(), value.encode())
