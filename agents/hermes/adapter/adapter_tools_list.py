from __future__ import annotations

from typing import Any

from adapter_config import MAX_TOOL_LIST_PAGES, AdapterError


class _ToolsListMixin:
    def _tools_list(self, message: dict[str, Any]) -> dict[str, Any] | None:
        """Return every target's manifest tools, paging the gateway to exhaustion.

        AgentCore pages `tools/list`: the result carries `nextCursor` alongside
        `tools`, and the page size is size-based, so the first page is not the
        tool set. Reading only the first page makes a complete catalog look
        partial -- the tools on the later pages are still callable, which is
        what makes that misread so convincing.

        The exposed set is still asserted equal to the union of the manifests,
        so paging cannot widen the allowlist and a target that fails to appear
        is a mismatch rather than a silently smaller catalog. Any cursor the
        client sends is ignored: this adapter never emits one, because it
        returns the whole set at once.
        """
        if "id" not in message:
            return None
        safe_tools: list[dict[str, Any]] = []
        seen: set[str] = set()
        first_response: dict[str, Any] | None = None
        result: dict[str, Any] = {}
        cursor: str | None = None
        for _ in range(MAX_TOOL_LIST_PAGES):
            page_request = dict(message)
            page_request["params"] = {"cursor": cursor} if cursor else {}
            page, _headers = self._send(page_request)
            if page is None:
                raise AdapterError("invalid_gateway_response")
            if page.get("error"):
                return page
            if first_response is None:
                first_response = page
            page_result = page.get("result")
            tools = page_result.get("tools") if isinstance(page_result, dict) else None
            if not isinstance(page_result, dict) or not isinstance(tools, list):
                raise AdapterError("invalid_gateway_response")
            result = page_result
            for tool in tools:
                if not isinstance(tool, dict) or not isinstance(tool.get("name"), str):
                    raise AdapterError("invalid_gateway_response")
                name = tool["name"]
                target = self._target_for_action(name)
                if target is None:
                    # A target this adapter does not register. Not an error and
                    # never exposed; the equality check below is what enforces
                    # the allowlist.
                    continue
                logical_name = name[len(target.prefix) :]
                client_name = f"{target.client_tool_prefix}{logical_name}"
                # Expose only the owning target's manifest allowlist, even if
                # the gateway or an upstream returns additional tools.
                if logical_name not in target.tools or client_name in seen:
                    continue
                exposed = dict(tool)
                exposed["name"] = client_name
                safe_tools.append(exposed)
                seen.add(client_name)
            cursor = page_result.get("nextCursor")
            if not isinstance(cursor, str) or not cursor:
                break
        else:
            raise AdapterError("gateway_tool_pagination_limit")
        if seen != set(self._owners) or len(safe_tools) != len(self._owners):
            raise AdapterError("gateway_tool_set_mismatch")
        assert first_response is not None
        # Drop nextCursor: the client is being handed the complete set, so
        # there is nothing further to fetch.
        output = {key: value for key, value in result.items() if key != "nextCursor"}
        output["tools"] = safe_tools
        response = {**first_response, "result": output}
        return response