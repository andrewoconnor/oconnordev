"""Optional SDK proof; run with an isolated MCP installation, never production HTTP.

The explicit strict contract reproduces the daemon's object-root validation.
Do not mistake SDK versions with dict-valued outputSchema for strict clients.
"""

import importlib.util
import pathlib
import sys
import unittest
from typing import Literal

from .output_schema_stdio import INCOMPATIBLE_SCHEMAS, OBJECT_SCHEMA
from .test_support import EXPECTED_TOOLS


@unittest.skipUnless(importlib.util.find_spec("mcp"), "optional MCP SDK not installed")
class SDKDiscoveryTests(unittest.TestCase):
    def test_real_stdio_initialize_and_list_tools_satisfy_strict_contract(self):
        import anyio
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        from pydantic import BaseModel, ConfigDict, ValidationError

        class ObjectSchema(BaseModel):
            type: Literal["object"]
            model_config = ConfigDict(extra="allow")

        class StrictTool(BaseModel):
            name: str
            outputSchema: ObjectSchema | None = None
            model_config = ConfigDict(extra="allow")

        class StrictListToolsResult(BaseModel):
            tools: list[StrictTool]

        for schema in INCOMPATIBLE_SCHEMAS:
            with self.assertRaises(ValidationError):
                StrictTool.model_validate({"name": "upstream", "outputSchema": schema})

        async def discover():
            params = StdioServerParameters(
                command=sys.executable,
                args=["-m", "test.output_schema_stdio"],
                cwd=str(pathlib.Path(__file__).resolve().parent.parent),
                env={},
            )
            with anyio.fail_after(15):
                async with (
                    stdio_client(params) as (reader, writer),
                    ClientSession(reader, writer) as session,
                ):
                    initialized = await session.initialize()
                    self.assertEqual(
                        initialized.model_dump(by_alias=True)["serverInfo"]["name"],
                        "offline-agentcore-fixture",
                    )
                    result = await session.list_tools()
                    document = result.model_dump(by_alias=True, exclude_none=True)
                    strict = StrictListToolsResult.model_validate(document)
                    self.assertEqual(
                        {tool.name for tool in strict.tools}, EXPECTED_TOOLS
                    )
                    schemas = [tool.get("outputSchema") for tool in document["tools"]]
                    self.assertEqual(schemas.count(None), len(INCOMPATIBLE_SCHEMAS))
                    self.assertTrue(
                        all(s is None or s == OBJECT_SCHEMA for s in schemas)
                    )
                    called = await session.call_tool("aws___read_documentation", {})
                    self.assertEqual(called.content[0].text, "safe")

        anyio.run(discover)
