"""Offline stdio fixture: real adapter, synthetic paginated gateway, no HTTP."""

import json

from hermes_agentcore_adapter import serve

from .test_support import FakeTransport, _response, make_forwarder

OBJECT_SCHEMA = {
    "type": "object",
    "properties": {"value": {"type": ["null", "array"]}},
}
# Reproduce the nine failing roots in the discovery log, not private tool data.
INCOMPATIBLE_SCHEMAS = [
    {"type": ["null", "object"]},
    {"oneOf": [{"type": "object"}, {"type": "null"}]},
    {"type": ["null", "object"]},
    {"oneOf": [{"type": "null"}, {"type": "object"}]},
    {"oneOf": [{"type": "null"}, {"type": "object"}]},
    {"type": ["null", "array"]},
    {"type": ["null", "object"]},
    {"oneOf": [{"type": "null"}, {"type": "object"}]},
    {"type": ["null", "object"]},
]


class SchemaTransport(FakeTransport):
    def __init__(self):
        super().__init__()
        self.page_size = 3
        self.schemas = dict(zip(self._catalog(), INCOMPATIBLE_SCHEMAS, strict=False))

    def request(self, url, method, headers, body):
        response = super().request(url, method, headers, body)
        message = json.loads(body) if method == "POST" and body.startswith(b"{") else {}
        if message.get("method") == "tools/list":
            document = json.loads(response.body)
            for tool in document["result"]["tools"]:
                tool.update(
                    inputSchema={"type": "object", "properties": {}},
                    outputSchema=self.schemas.get(tool["name"], OBJECT_SCHEMA),
                    annotations={"readOnlyHint": True},
                )
            return _response(response.status, document, response.headers)
        if message.get("method") == "initialize":
            document = json.loads(response.body)
            document["result"].update(
                capabilities={"tools": {}},
                serverInfo={"name": "offline-agentcore-fixture", "version": "1"},
            )
            return _response(response.status, document, response.headers)
        return response


if __name__ == "__main__":
    serve(forwarder=make_forwarder(SchemaTransport()))
