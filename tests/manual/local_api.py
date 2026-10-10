import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from threading import Thread
from typing import Any, Dict
from zipfile import ZipFile


class LocalToolbox:
    """Deterministic catalog/task service; no credentials or external mutations."""

    def __enter__(self):
        tool = {
            "id": 1,
            "name": "hello",
            "alias": "Integration demo",
            "description": "Local desktop integration test",
            "docs": "<p>Demo documentation</p>",
            "can_run": True,
            "is_dev": False,
            "is_free": True,
            "is_new": False,
            "is_featured": False,
            "is_favorite": False,
            "tags": [1],
            "inputs": [{"name": "sleep", "type": "int", "required": False}],
            "outputs": [
                {"name": "message", "type": "string", "required": True}
            ],
        }
        presets = {
            "items": [{"alias": "Demo", "inputs": {"sleep": 0}, "outputs": {}}]
        }
        file_tool: Dict[str, Any] = dict(
            tool, id=2, name="geocodetable", alias="File integration demo"
        )
        file_tool["inputs"] = [
            {"name": "table", "type": "file", "required": True},
            {"name": "addr_field", "type": "string", "required": True},
        ]
        file_tool["outputs"] = [
            {"name": "result_file", "type": "file", "required": True}
        ]
        file_presets = {
            "items": [
                {
                    "alias": "Demo",
                    "inputs": {
                        "table": {
                            "name": "demo.csv",
                            "local": {"uuid": "demo"},
                        },
                        "addr_field": "address",
                    },
                    "outputs": {},
                }
            ]
        }
        buffer = BytesIO()
        with ZipFile(buffer, "w") as archive:
            archive.writestr("result.csv", "address,lon,lat\nDemo,1,2\n")
        archive_bytes = buffer.getvalue()
        requests = []
        self.requests = requests
        submissions = []
        self.submissions = submissions

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                del format, args

            def do_HEAD(self):
                self.do_GET(send_body=False)

            def do_GET(self, send_body=True):
                path = self.path.split("?", 1)[0].rstrip("/")
                requests.append((self.command, path))
                if path == "/api/download/storage/demo":
                    self.respond_bytes(
                        b"address\nDemo\n", "demo.csv", send_body
                    )
                    return
                if path == "/api/download/storage/result.file":
                    self.respond_bytes(archive_bytes, "result.file", send_body)
                    return
                payloads = {
                    "/api/tags": {
                        "data": [{"id": 1, "alias": "Demo", "icon": "tools"}]
                    },
                    "/api/tools": {"data": [tool, file_tool]},
                    "/api/tools/hello": tool,
                    "/api/tools/hello/presets": presets,
                    "/api/tools/geocodetable": file_tool,
                    "/api/tools/geocodetable/presets": file_presets,
                    "/api/tasks/file-task": {
                        "state": "SUCCESS",
                        "status": "SUCCESS",
                        "progress": 100,
                        "tool": "geocodetable",
                        "operation": "geocodetable",
                        "error": None,
                        "output": [
                            {
                                "name": "result_file",
                                "type": "file",
                                "value": "storage/result.file",
                            }
                        ],
                    },
                    "/api/tasks/task-1": {
                        "state": "SUCCESS",
                        "status": "SUCCESS",
                        "progress": 100,
                        "tool": "hello",
                        "operation": "hello",
                        "error": None,
                        "output": [
                            {
                                "name": "message",
                                "type": "string",
                                "value": "hello",
                            }
                        ],
                    },
                }
                self.respond(
                    payloads.get(path), 200 if path in payloads else 404
                )

            def do_POST(self):
                body = self.rfile.read(
                    int(self.headers.get("Content-Length", "0"))
                )
                path = self.path.split("?", 1)[0].rstrip("/")
                requests.append((self.command, path))
                if path == "/api/upload":
                    self.respond(
                        {
                            "name": "demo.csv",
                            "local": {"uuid": "uploaded"},
                            "s3": None,
                        },
                        200,
                    )
                    return
                if (
                    path == "/api/tasks"
                    and json.loads(body)["tool"] == "geocodetable"
                ):
                    submissions.append(json.loads(body))
                    self.respond({"task_id": "file-task"}, 200)
                    return
                if path == "/api/tasks":
                    submissions.append(json.loads(body))
                self.respond(
                    {"task_id": "task-1"}, 200 if path == "/api/tasks" else 404
                )

            def respond(self, payload, status):
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def respond_bytes(self, body, filename, send_body):
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header(
                    "Content-Disposition", f'attachment; filename="{filename}"'
                )
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if send_body:
                    self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.endpoint = "http://127.0.0.1:" + str(self.server.server_port)
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
