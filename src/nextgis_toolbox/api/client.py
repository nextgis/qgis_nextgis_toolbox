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

import json
import re
from hashlib import sha256
from pathlib import Path
from threading import RLock
from time import perf_counter
from typing import Any, Dict, Optional
from urllib.parse import unquote

from qgis.core import (
    QgsFeedback,
    QgsNetworkAccessManager,
)
from qgis.PyQt.QtCore import (
    QEventLoop,
    QIODevice,
    QObject,
    QSaveFile,
    QUrl,
    QUrlQuery,
    pyqtSignal,
)
from qgis.PyQt.QtNetwork import (
    QNetworkReply,
    QNetworkRequest,
)

from nextgis_toolbox.api.authentication import (
    ToolboxAuthentication,
)
from nextgis_toolbox.api.cache_manager import CacheManager
from nextgis_toolbox.core import utils
from nextgis_toolbox.core.constants import DEFAULT_API_ENDPOINT
from nextgis_toolbox.core.exceptions import (
    ToolboxAuthenticationError,
    ToolboxCacheError,
    ToolboxError,
    ToolboxFileWriteError,
    ToolboxNetworkError,
    ToolboxRequestCanceledError,
)
from nextgis_toolbox.core.logging import logger
from nextgis_toolbox.core.qt_network_error import (
    QtNetworkError,
)
from nextgis_toolbox.core.utils import assert_not_none
from nextgis_toolbox.settings.nextgis_toolbox_settings import (
    AuthenticationType,
)


class RequestResultStatus:
    SUCCESS = "success"
    FAILED = "failed"
    CANCELED = "canceled"


class ToolboxApiClient(QObject):
    """Low-level HTTP client for NextGIS Toolbox API."""

    endpoint_changed = pyqtSignal()
    authentication_changed = pyqtSignal()

    def __init__(
        self,
        parent: Optional[QObject] = None,
        qgis_profile: str = "default",
        endpoint: str = DEFAULT_API_ENDPOINT,
        authentication: Optional[ToolboxAuthentication] = None,
        cache_manager: Optional[CacheManager] = None,
    ) -> None:
        """Initialize API client."""
        super().__init__(parent)
        self._qgis_profile = qgis_profile
        self._endpoint = endpoint
        self._authentication = authentication
        self._is_custom_cache_manager = cache_manager is not None
        self._cache_lock = RLock()
        self._cache_manager = cache_manager or self._create_cache_manager()

    @property
    def endpoint(self) -> str:
        """Get current API endpoint URL."""
        return self._endpoint

    @endpoint.setter
    def endpoint(self, endpoint: str) -> None:
        """
        Set API endpoint URL.

        :param endpoint: Base URL for API requests.
        """
        if self._endpoint == endpoint:
            return

        self._endpoint = endpoint
        self._refresh_cache_manager()
        self.endpoint_changed.emit()

    @property
    def authentication_type(self) -> AuthenticationType:
        """Get current authentication type."""
        if self._authentication is None:
            return AuthenticationType.NONE

        return self._authentication.TYPE

    @property
    def authentication(self) -> Optional[ToolboxAuthentication]:
        """Get current authentication object."""
        return self._authentication

    @authentication.setter
    def authentication(
        self, authentication: Optional[ToolboxAuthentication] = None
    ) -> None:
        """
        Set current authentication object.

        :param authentication: Authentication object to use.
        """
        if self._authentication == authentication:
            return

        self._authentication = authentication
        self._refresh_cache_manager()
        self.authentication_changed.emit()

    def invalidate_cache(self) -> None:
        with self._cache_lock:
            try:
                self._cache_manager.invalidate()
            except ToolboxCacheError as error:
                logger.warning(error.log_message)

    def invalidate_cache_entry(self, cache_key: str) -> None:
        with self._cache_lock:
            try:
                self._cache_manager.invalidate_entry(cache_key)
            except ToolboxCacheError as error:
                logger.warning(error.log_message)

    def get(
        self,
        path: str,
        query_params: Optional[Dict[str, Any]] = None,
        feedback: Optional[QgsFeedback] = None,
        cache_key: Optional[str] = None,
        cache_ttl_hours: Optional[int] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Execute GET request and return parsed JSON.

        :param path: Relative API path or absolute URL.
        :param query_params: Optional query parameters.
        :param feedback: Optional feedback object for progress reporting.

        :returns: Parsed JSON response.
        """
        if cache_key is not None:
            cached_payload = self._cached_json(
                cache_key,
                cache_ttl_hours=cache_ttl_hours,
            )
            if cached_payload is not None:
                return cached_payload

        response_bytes = self.get_bytes(
            path=path,
            query_params=query_params,
            feedback=feedback,
            cache_key=cache_key,
            cache_ttl_hours=cache_ttl_hours,
            headers=headers,
        )

        return self._parse_json_response(
            response_bytes,
            context=f"GET {path}",
        )

    def get_bytes(
        self,
        path: str,
        query_params: Optional[Dict[str, Any]] = None,
        feedback: Optional[QgsFeedback] = None,
        cache_key: Optional[str] = None,
        cache_ttl_hours: Optional[int] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> bytes:
        """
        Execute GET request and return raw binary content.

        :param path: Relative API path or absolute URL.
        :param query_params: Optional query parameters.
        :param feedback: Optional feedback object for progress reporting.

        :returns: Raw response content.
        """
        cached_content = self._cached_bytes(
            cache_key,
            cache_ttl_hours=cache_ttl_hours,
        )
        if cached_content is not None:
            return cached_content

        request = self._build_request(
            path,
            query_params,
            headers=headers,
        )
        request_url = request.url().toString()
        started_at = self._log_request_started("GET", request_url, "↓")
        status = RequestResultStatus.SUCCESS

        try:
            response = QgsNetworkAccessManager.instance().blockingGet(
                request, feedback=feedback, forceRefresh=True
            )

            self._raise_if_request_canceled(feedback)
            self._raise_for_network_error(response.error())
            content = response.content().data()
            self._cache_bytes(cache_key, content)
            return content
        except ToolboxRequestCanceledError:
            status = RequestResultStatus.CANCELED
            raise
        except Exception:
            status = RequestResultStatus.FAILED
            raise
        finally:
            self._log_request_completed("GET", request_url, started_at, status)

    def upload(
        self,
        source_path: Path,
        feedback: Optional[QgsFeedback] = None,
    ) -> Dict[str, Any]:
        """Upload a file to Toolbox storage.

        :param source_path: Source file path.
        :param feedback: Optional feedback object for progress reporting.

        :returns: Uploaded file metadata.
        """
        file_path = Path(source_path)
        request = self._build_request(
            "upload",
            query_params={
                "filename": file_path.name,
                "format": "json",
            },
            with_language=False,
        )
        request.setRawHeader(
            b"Content-Type",
            b"application/octet-stream",
        )
        request_url = request.url().toString()
        started_at = self._log_request_started("UPLOAD", request_url, "↑")
        status = RequestResultStatus.SUCCESS

        try:
            payload_bytes = self._read_upload_payload(file_path)
            response = self._blocking_post(
                request,
                payload_bytes,
                feedback=feedback,
            )

            self._raise_if_request_canceled(feedback)
            self._raise_for_network_error(response.error())

            return self._parse_json_response(
                response.content().data(),
                context=f"UPLOAD {request_url}",
            )
        except ToolboxRequestCanceledError:
            status = RequestResultStatus.CANCELED
            raise
        except ToolboxError:
            status = RequestResultStatus.FAILED
            raise
        except Exception as error:
            status = RequestResultStatus.FAILED
            wrapped_error = ToolboxNetworkError(
                log_message=f"Unexpected upload failure for '{request_url}'",
            )
            wrapped_error.add_note(f"Technical details: {error}")
            raise wrapped_error from error
        finally:
            self._log_request_completed(
                "UPLOAD",
                request_url,
                started_at,
                status,
            )

    def download(
        self,
        path: str,
        destination_path: Path,
        query_params: Optional[Dict[str, Any]] = None,
        feedback: Optional[QgsFeedback] = None,
    ) -> Path:
        """Download response content directly to the destination path.

        :param path: Relative API path or absolute URL.
        :param destination_path: Target file path.
        :param query_params: Optional query parameters.
        :param feedback: Optional feedback object for progress reporting.

        :returns: Saved file path.
        """
        request = self._build_download_request(path, query_params)
        request_url = request.url().toString()
        started_at = self._log_request_started("DOWNLOAD", request_url, "↓")
        status = RequestResultStatus.SUCCESS

        try:
            filename = self._fetch_download_filename(request, feedback)
            saved_path = self._resolve_download_path(
                destination_path, filename
            )
            self._ensure_download_directory(saved_path)
            output_file = self._open_download_file(saved_path)
            reply = self._start_download_reply(request, feedback)

            try:
                self._execute_download(
                    reply,
                    output_file,
                    saved_path,
                    feedback,
                )
            except Exception:
                output_file.cancelWriting()
                raise
            finally:
                reply.deleteLater()

            return saved_path
        except ToolboxRequestCanceledError:
            status = RequestResultStatus.CANCELED
            raise
        except Exception:
            status = RequestResultStatus.FAILED
            raise
        finally:
            self._log_request_completed(
                "DOWNLOAD",
                request_url,
                started_at,
                status,
            )

    def post(
        self,
        path: str,
        payload: Dict[str, Any],
        feedback: Optional[QgsFeedback] = None,
    ) -> Dict[str, Any]:
        """
        Execute POST request with JSON payload.

        :param path: Relative API path or absolute URL.
        :param payload: Request payload.
        :param feedback: Optional feedback object for progress reporting.

        :returns: Parsed JSON response.
        """
        request = self._build_request(path)
        request_url = request.url().toString()
        started_at = self._log_request_started("POST", request_url, "↑")
        status = RequestResultStatus.SUCCESS

        try:
            payload_bytes = self._serialize_json_payload(
                payload,
                context=f"POST {request_url}",
            )
            response = self._blocking_post(
                request,
                payload_bytes,
                feedback=feedback,
            )

            self._raise_if_request_canceled(feedback)
            self._raise_for_network_error(response.error())

            return self._parse_json_response(
                response.content().data(),
                context=f"POST {request_url}",
            )
        except ToolboxRequestCanceledError:
            status = RequestResultStatus.CANCELED
            raise
        except ToolboxError:
            status = RequestResultStatus.FAILED
            raise
        except Exception as error:
            status = RequestResultStatus.FAILED
            wrapped_error = ToolboxNetworkError(
                log_message=f"Unexpected POST failure for '{request_url}'",
            )
            wrapped_error.add_note(f"Technical details: {error}")
            raise wrapped_error from error
        finally:
            self._log_request_completed(
                "POST", request_url, started_at, status
            )

    def _blocking_post(
        self,
        request: QNetworkRequest,
        payload_bytes: bytes,
        feedback: Optional[QgsFeedback] = None,
    ) -> Any:
        network_manager = QgsNetworkAccessManager.instance()
        return network_manager.blockingPost(
            request,
            payload_bytes,
            None,
            True,
            feedback,
        )

    def _build_request(
        self,
        path: str,
        query_params: Optional[Dict[str, Any]] = None,
        with_language: bool = True,
        headers: Optional[Dict[str, str]] = None,
    ) -> QNetworkRequest:
        """
        Create configured API request.

        :param path: Relative API path or absolute URL.
        :param query_params: Optional query parameters.

        :returns: Configured request.
        """
        query_url_params = QUrlQuery()
        if with_language:
            query_url_params.addQueryItem("lang", utils.qgis_locale())
        query_params = {} if query_params is None else query_params
        for key, value in query_params.items():
            query_url_params.addQueryItem(str(key), str(value))

        qurl = self._build_url(path)
        qurl.setQuery(query_url_params)

        request = QNetworkRequest(qurl)
        request_headers = {
            "Content-Type": "application/json",
            "Accept-Language": utils.qgis_locale(),
        }
        if headers is not None:
            request_headers.update(headers)

        self._apply_headers(request, request_headers)
        self._apply_authentication(request)

        return request

    def _build_download_request(
        self,
        path: str,
        query_params: Optional[Dict[str, Any]] = None,
    ) -> QNetworkRequest:
        """Create configured request for file downloads."""
        query_url_params = QUrlQuery()
        query_params = {} if query_params is None else query_params
        for key, value in query_params.items():
            query_url_params.addQueryItem(str(key), str(value))

        qurl = self._build_download_url(path)
        qurl.setQuery(query_url_params)

        request = QNetworkRequest(qurl)
        self._apply_headers(
            request,
            {"Accept-Language": utils.qgis_locale()},
        )
        self._apply_authentication(request)

        return request

    def _build_url(self, path: str) -> QUrl:
        """Create URL for relative API path or absolute URL.

        :param path: Relative API path or absolute URL.

        :returns: Qt URL instance.
        """
        qurl = QUrl(path)
        if qurl.isValid() and not qurl.isRelative():
            return qurl

        return QUrl(f"{self._endpoint.rstrip('/')}/api/{path.lstrip('/')}")

    def _build_download_url(self, path: str) -> QUrl:
        """Create URL for download endpoint or absolute URL."""
        qurl = QUrl(path)
        if qurl.isValid() and not qurl.isRelative():
            return qurl

        normalized_path = path.lstrip("/")
        if normalized_path.startswith("api/"):
            return QUrl(f"{self._endpoint.rstrip('/')}/{normalized_path}")

        if normalized_path.startswith("download/"):
            return QUrl(f"{self._endpoint.rstrip('/')}/api/{normalized_path}")

        return QUrl(
            f"{self._endpoint.rstrip('/')}/api/download/{normalized_path}"
        )

    def _log_request_started(
        self,
        method: str,
        request_url: str,
        direction: str,
    ) -> float:
        """Log request start and return a timer origin."""
        logger.debug(f"{direction} {method} {request_url}")
        return perf_counter()

    def _log_request_completed(
        self,
        method: str,
        request_url: str,
        started_at: float,
        status: str,
    ) -> None:
        """Log request completion with elapsed time."""
        elapsed_seconds = perf_counter() - started_at
        logger.debug(
            f"✓ {method} {request_url} finished with status "
            f"'{status}' in {elapsed_seconds:.3f}s"
        )

    def _fetch_download_filename(
        self,
        request: QNetworkRequest,
        feedback: Optional[QgsFeedback],
    ) -> Optional[str]:
        """Try to resolve the final download filename from response headers."""
        request_url = request.url().toString()
        started_at = self._log_request_started("HEAD", request_url, "↓")
        status = RequestResultStatus.SUCCESS
        reply = assert_not_none(
            QgsNetworkAccessManager.instance().head(request),
            "Failed to start HEAD request",
        )
        event_loop = QEventLoop(self)

        if feedback is not None:
            feedback.canceled.connect(reply.abort)

        reply.finished.connect(event_loop.quit)

        try:
            event_loop.exec()
            self._raise_if_request_canceled(feedback)

            if self._is_optional_head_failure(reply):
                return None

            self._raise_for_network_error(reply.error())
            return self._extract_filename_from_reply(reply)
        except ToolboxRequestCanceledError:
            status = RequestResultStatus.CANCELED
            raise
        except ToolboxError:
            status = RequestResultStatus.FAILED
            raise
        except Exception as error:
            status = RequestResultStatus.FAILED
            wrapped_error = ToolboxNetworkError(
                log_message=(
                    f"Unexpected HEAD failure while resolving '{request_url}'"
                ),
            )
            wrapped_error.add_note(f"Technical details: {error}")
            raise wrapped_error from error
        finally:
            reply.deleteLater()
            self._log_request_completed(
                "HEAD",
                request_url,
                started_at,
                status,
            )

    def _is_optional_head_failure(self, reply: QNetworkReply) -> bool:
        """Return whether a failed HEAD request can be ignored."""
        if reply.error() == QNetworkReply.NetworkError.NoError:
            return False

        status_code = reply.attribute(
            QNetworkRequest.Attribute.HttpStatusCodeAttribute
        )
        return status_code in (405, 501)

    def _extract_filename_from_reply(
        self,
        reply: QNetworkReply,
    ) -> Optional[str]:
        """Extract download filename from response headers."""
        header_value = (
            reply.rawHeader(b"Content-Disposition")
            .data()
            .decode(
                "utf-8",
                errors="ignore",
            )
        )
        if not header_value:
            return None

        return self._extract_filename_from_content_disposition(header_value)

    def _extract_filename_from_content_disposition(
        self,
        header_value: str,
    ) -> Optional[str]:
        """Extract filename from content disposition header value."""
        filename_match = re.search(
            r"filename\*=UTF-8''([^;]+)|filename=\"([^\"]+)\"|filename=([^;]+)",
            header_value,
        )
        if filename_match is None:
            return None

        filename = (
            filename_match.group(1)
            or filename_match.group(2)
            or filename_match.group(3)
        )
        return unquote(filename.strip()) if filename is not None else None

    def _resolve_download_path(
        self,
        destination_path: Path,
        filename: Optional[str],
    ) -> Path:
        """Resolve destination path for a downloaded file."""
        saved_path = Path(destination_path)
        if filename is None:
            return saved_path

        if saved_path.exists() and saved_path.is_dir():
            return saved_path / filename

        if saved_path.suffix:
            return saved_path

        if saved_path.exists() and not saved_path.is_dir():
            return saved_path

        return saved_path / filename

    def _ensure_download_directory(self, saved_path: Path) -> None:
        """Ensure destination directory exists."""
        try:
            saved_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            wrapped_error = ToolboxFileWriteError(
                log_message=f"Failed to prepare directory for '{saved_path}'."
            )
            wrapped_error.add_note(f"Technical details: {error}")
            raise wrapped_error from error

    def _open_download_file(self, saved_path: Path) -> QSaveFile:
        """Open destination file for streamed download."""
        output_file = QSaveFile(str(saved_path))
        if not output_file.open(QIODevice.OpenModeFlag.WriteOnly):
            wrapped_error = ToolboxFileWriteError(
                log_message=f"Failed to open '{saved_path}' for writing."
            )
            error_string = output_file.errorString().strip()
            if error_string:
                wrapped_error.add_note(f"Technical details: {error_string}")
            raise wrapped_error

        return output_file

    def _start_download_reply(
        self,
        request: QNetworkRequest,
        feedback: Optional[QgsFeedback],
    ) -> QNetworkReply:
        """Start download request."""
        reply = assert_not_none(
            QgsNetworkAccessManager.instance().get(request),
            "Failed to start download request",
        )
        if feedback is not None:
            feedback.canceled.connect(reply.abort)

        return reply

    def _execute_download(
        self,
        reply: QNetworkReply,
        output_file: QSaveFile,
        saved_path: Path,
        feedback: Optional[QgsFeedback],
    ) -> None:
        """Stream reply data to file and finalize the download."""
        event_loop = QEventLoop(self)
        write_error: Optional[Exception] = None

        def write_available_data() -> None:
            nonlocal write_error
            write_error = self._write_download_chunk(
                reply,
                output_file,
                saved_path,
                write_error,
            )
            if write_error is not None:
                reply.abort()

        reply.readyRead.connect(write_available_data)
        reply.finished.connect(write_available_data)
        reply.finished.connect(event_loop.quit)
        event_loop.exec()

        if write_error is not None:
            raise write_error

        self._raise_if_request_canceled(feedback)
        self._raise_for_network_error(reply.error())
        self._commit_download_file(output_file, saved_path)

    def _write_download_chunk(
        self,
        reply: QNetworkReply,
        output_file: QSaveFile,
        saved_path: Path,
        current_error: Optional[Exception],
    ) -> Optional[Exception]:
        """Write the next available chunk from reply to disk."""
        if current_error is not None:
            return current_error

        chunk = reply.readAll()
        if chunk.isEmpty():
            return None

        chunk_bytes = chunk.data()
        written_bytes = output_file.write(chunk_bytes)
        if written_bytes == len(chunk_bytes):
            return None

        wrapped_error = ToolboxFileWriteError(
            log_message=f"Failed to write downloaded data to '{saved_path}'."
        )
        error_string = output_file.errorString().strip()
        if error_string:
            wrapped_error.add_note(f"Technical details: {error_string}")
        return wrapped_error

    def _commit_download_file(
        self,
        output_file: QSaveFile,
        saved_path: Path,
    ) -> None:
        """Commit streamed file to the final location."""
        if output_file.commit():
            return

        wrapped_error = ToolboxFileWriteError(
            log_message=f"Failed to save downloaded file to '{saved_path}'."
        )
        error_string = output_file.errorString().strip()
        if error_string:
            wrapped_error.add_note(f"Technical details: {error_string}")
        raise wrapped_error

    def _raise_if_request_canceled(
        self,
        feedback: Optional[QgsFeedback],
    ) -> None:
        """Raise an exception if the request was canceled by the user."""
        if feedback is None or not feedback.isCanceled():
            return

        raise ToolboxRequestCanceledError(
            log_message="Network request was canceled by user",
        )

    def _raise_for_network_error(
        self,
        network_error: QNetworkReply.NetworkError,
    ) -> None:
        """Raise a typed exception for a Qt network error."""
        if network_error == QNetworkReply.NetworkError.NoError:
            return

        qt_network_error = QtNetworkError.from_qt(network_error)

        if network_error in (
            QNetworkReply.NetworkError.AuthenticationRequiredError,
            QNetworkReply.NetworkError.ProxyAuthenticationRequiredError,
        ):
            wrapped_error = ToolboxAuthenticationError(
                log_message="Toolbox API authentication failed"
            )
            self._add_network_error_notes(wrapped_error, qt_network_error)
            raise wrapped_error

        if network_error == QNetworkReply.NetworkError.OperationCanceledError:
            wrapped_error = ToolboxRequestCanceledError(
                log_message="Network request was canceled"
            )
            self._add_network_error_notes(wrapped_error, qt_network_error)
            raise wrapped_error

        wrapped_error = ToolboxNetworkError(
            log_message="Network request failed",
        )
        self._add_network_error_notes(wrapped_error, qt_network_error)
        raise wrapped_error

    def _apply_headers(
        self, request: QNetworkRequest, headers: Dict[str, str]
    ) -> None:
        """
        Apply given headers to the request.

        :param request: Network request to apply headers to.
        :param headers: Dictionary of headers to apply.
        """
        for header_name, header_value in headers.items():
            request.setRawHeader(header_name.encode(), header_value.encode())

    def _apply_authentication(self, request: QNetworkRequest) -> None:
        """
        Apply current authentication to the given request.

        :param request: Network request to apply authentication to.
        """
        if self._authentication is not None:
            self._authentication.apply(request)

    def _create_cache_manager(self) -> CacheManager:
        return CacheManager(
            self._cache_scope_id(),
            qgis_profile=self._qgis_profile,
        )

    def _refresh_cache_manager(self) -> None:
        if self._is_custom_cache_manager:
            return

        with self._cache_lock:
            self._cache_manager = self._create_cache_manager()

    def _cache_scope_id(self) -> str:
        authentication_headers = {}
        if self._authentication is not None:
            authentication_headers = self._authentication.headers

        cache_source = json.dumps(
            {
                "authentication": authentication_headers,
                "authentication_type": str(self.authentication_type),
                "endpoint": self._endpoint,
            },
            sort_keys=True,
        )
        return sha256(cache_source.encode("utf-8")).hexdigest()

    def _cached_bytes(
        self,
        cache_key: Optional[str],
        cache_ttl_hours: Optional[int] = None,
    ) -> Optional[bytes]:
        if cache_key is None:
            return None

        with self._cache_lock:
            try:
                return self._cache_manager.get_bytes(
                    cache_key,
                    cache_ttl_hours=cache_ttl_hours,
                )
            except ToolboxCacheError as error:
                logger.warning(error.log_message)
                return None

    def _cached_json(
        self,
        cache_key: str,
        cache_ttl_hours: Optional[int] = None,
    ) -> Optional[Any]:
        with self._cache_lock:
            try:
                return self._cache_manager.get(
                    cache_key,
                    cache_ttl_hours=cache_ttl_hours,
                )
            except ToolboxCacheError as error:
                logger.warning(error.log_message)
                return None

    def _cache_bytes(
        self,
        cache_key: Optional[str],
        content: bytes,
    ) -> None:
        if cache_key is None:
            return

        with self._cache_lock:
            try:
                self._cache_manager.put_bytes(cache_key, content)
            except ToolboxCacheError as error:
                logger.warning(error.log_message)

    def _read_upload_payload(self, file_path: Path) -> bytes:
        try:
            return file_path.read_bytes()
        except OSError as error:
            wrapped_error = ToolboxError(
                log_message=f"Failed to read upload file '{file_path}'.",
                user_message=self.tr("Failed to read the file for upload."),
            )
            wrapped_error.add_note(f"Technical details: {error}")
            raise wrapped_error from error

    def _serialize_json_payload(
        self,
        payload: Dict[str, Any],
        *,
        context: str,
    ) -> bytes:
        try:
            return json.dumps(payload).encode()
        except (TypeError, ValueError) as error:
            wrapped_error = ToolboxError(
                log_message=(
                    f"Failed to serialize JSON payload for '{context}'."
                ),
                user_message=self.tr("Failed to prepare the request payload."),
            )
            wrapped_error.add_note(f"Technical details: {error}")
            raise wrapped_error from error

    def _parse_json_response(
        self,
        response_bytes: bytes,
        *,
        context: str,
    ) -> Dict[str, Any]:
        try:
            return json.loads(response_bytes.decode())
        except (TypeError, ValueError, UnicodeDecodeError) as error:
            wrapped_error = ToolboxNetworkError(
                log_message=(
                    f"Failed to decode JSON response for '{context}'."
                ),
            )
            wrapped_error.add_note(f"Technical details: {error}")
            raise wrapped_error from error

    def _add_network_error_notes(
        self,
        error: ToolboxError,
        qt_network_error: Optional[QtNetworkError],
    ) -> None:
        if qt_network_error is None:
            error.add_note("Network error: Unknown Qt network error")
            return

        qt_network_error.value.add_exception_notes(error)
