"""Client for asya gateway MCP server."""

import json
import sys
from typing import Any
from urllib.parse import urljoin


try:
    import requests
    from tqdm import tqdm
except ImportError:
    print("[!] Missing dependencies. Install with:")
    print("    uv pip install requests tqdm")
    sys.exit(1)


class AsyaGatewayClient:
    """Client for asya gateway MCP server."""

    def __init__(self, base_url: str = "http://localhost:8089"):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        self.mcp_session_id: str | None = None

    def _post(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        """POST request with error handling."""
        url = urljoin(self.base_url + "/", path.lstrip("/"))
        try:
            resp = self.session.post(url, json=data, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as e:
            print(f"[-] Request failed: {e}", file=sys.stderr)
            print(f"[-] Request payload: {json.dumps(data)}", file=sys.stderr)
            print(f"[-] Server response: {e.response.text}", file=sys.stderr)
            sys.exit(1)
        except requests.exceptions.RequestException as e:
            print(f"[-] Request failed: {e}", file=sys.stderr)
            sys.exit(1)

    def _get(self, path: str) -> dict[str, Any]:
        """GET request with error handling."""
        url = urljoin(self.base_url + "/", path.lstrip("/"))
        try:
            resp = self.session.get(url, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as e:
            print(f"[-] Request failed: {e}", file=sys.stderr)
            print(f"[-] Server response: {e.response.text}", file=sys.stderr)
            sys.exit(1)
        except requests.exceptions.RequestException as e:
            print(f"[-] Request failed: {e}", file=sys.stderr)
            sys.exit(1)

    def _mcp_request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Make an MCP JSON-RPC request with session handling."""
        if params is None:
            params = {}

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params,
        }

        url = urljoin(self.base_url + "/", "mcp")
        headers: dict[str, str] = {}

        if self.mcp_session_id:
            headers["Mcp-Session-Id"] = self.mcp_session_id

        try:
            resp = self.session.post(url, json=payload, headers=headers, timeout=10)
            resp.raise_for_status()

            session_id = resp.headers.get("Mcp-Session-Id")
            if session_id:
                self.mcp_session_id = session_id

            result = resp.json()

            if "error" in result:
                error = result["error"]
                raise Exception(f"MCP error: {error.get('message', error)}")

            return result
        except requests.exceptions.HTTPError as e:
            print(f"[-] MCP request failed: {e}", file=sys.stderr)
            print(f"[-] Server response: {e.response.text}", file=sys.stderr)
            sys.exit(1)
        except requests.exceptions.RequestException as e:
            print(f"[-] Request failed: {e}", file=sys.stderr)
            sys.exit(1)

    def list_tools(self) -> dict[str, Any]:
        """List available tools via MCP protocol."""
        self._mcp_request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "asya-cli", "version": "1.0.0"},
            },
        )

        return self._mcp_request("tools/list", {})

    def show_tool(self, tool_name: str) -> dict[str, Any] | None:
        """Get detailed information about a specific tool."""
        tools_result = self.list_tools()
        tools = tools_result.get("result", {}).get("tools", [])

        for tool in tools:
            if tool.get("name") == tool_name:
                return tool

        return None

    def _tool_to_dict(self, tool: dict[str, Any], show_details: bool = False) -> dict[str, Any]:
        """Convert tool to dictionary format for YAML output."""
        result = {
            "name": tool.get("name", "?"),
            "description": tool.get("description", ""),
        }

        params = tool.get("inputSchema", {}).get("properties", {})
        if params:
            parameters = {}
            required_params = tool.get("inputSchema", {}).get("required", [])

            for param_name, param_spec in params.items():
                param_info = {
                    "type": param_spec.get("type", "any"),
                    "required": param_name in required_params,
                }

                if show_details:
                    if param_spec.get("description"):
                        param_info["description"] = param_spec["description"]
                    if "default" in param_spec:
                        param_info["default"] = param_spec["default"]
                    if "enum" in param_spec:
                        param_info["options"] = param_spec["enum"]

                parameters[param_name] = param_info

            result["parameters"] = parameters

        return result

    def _extract_envelope_id(self, mcp_result: dict[str, Any]) -> str | None:
        """Extract envelope_id from MCP CallToolResult format."""
        content = mcp_result.get("content", [])

        if content:
            for item in content:
                if item.get("type") == "text":
                    text = item.get("text", "")
                    try:
                        data = json.loads(text)
                        envelope_id = data.get("envelope_id")
                        if envelope_id:
                            return envelope_id
                    except (json.JSONDecodeError, AttributeError):
                        continue

        return mcp_result.get("envelope_id")

    def call_tool(
        self, tool_name: str, arguments: dict[str, Any], stream: bool = True, debug: bool = False
    ) -> dict[str, Any]:
        """
        Call a tool via REST endpoint.

        Args:
            tool_name: Name of the tool to call
            arguments: Tool arguments as dict
            stream: If True, stream via SSE. If False, return envelope ID immediately.
            debug: If True, print each SSE event as one-line JSON to stderr

        Returns:
            If stream=True: final result (with progress bar if tool reports progress)
            If stream=False: envelope creation response
        """
        payload = {"name": tool_name, "arguments": arguments}
        result = self._post("/tools/call", payload)

        if not stream:
            return result

        envelope_id = self._extract_envelope_id(result)
        if not envelope_id:
            return result

        print(f"[.] Envelope ID: {envelope_id}", file=sys.stderr)
        return self._stream_with_progress(envelope_id, debug=debug)

    def get_status(self, envelope_id: str) -> dict[str, Any]:
        """Get envelope status."""
        return self._get(f"/envelopes/{envelope_id}")

    def stream_updates(self, envelope_id: str) -> None:
        """Stream envelope updates via SSE."""
        url = urljoin(self.base_url + "/", f"envelopes/{envelope_id}/stream")
        try:
            with requests.get(url, stream=True, timeout=300) as resp:
                resp.raise_for_status()
                print(f"[.] Streaming updates for envelope {envelope_id}", file=sys.stderr)
                print("-" * 60, file=sys.stderr)

                for line in resp.iter_lines():
                    if not line:
                        continue
                    line = line.decode("utf-8")

                    if line.startswith("data: "):
                        data = line[6:]
                        try:
                            event = json.loads(data)
                            self._print_event(event)
                        except json.JSONDecodeError:
                            print(f"[.] {data}", file=sys.stderr)
        except requests.exceptions.RequestException as e:
            print(f"[-] Stream failed: {e}", file=sys.stderr)
            sys.exit(1)

    def _stream_with_progress(self, envelope_id: str, debug: bool = False) -> dict[str, Any]:
        """
        Stream envelope updates via SSE. Shows progress bar only if tool reports progress_percent.

        Args:
            envelope_id: Envelope ID to stream
            debug: If True, print each SSE event as one-line JSON to stderr

        Returns final envelope state as dict.
        """
        url = urljoin(self.base_url + "/", f"envelopes/{envelope_id}/stream")

        final_result = None
        progress_bar = None
        has_progress = False

        try:
            with requests.get(url, stream=True, timeout=300) as resp:
                resp.raise_for_status()

                for line in resp.iter_lines():
                    if not line:
                        continue
                    line = line.decode("utf-8")

                    if line.startswith("data: "):
                        data = line[6:]
                        try:
                            event = json.loads(data)

                            if debug:
                                print(json.dumps(event, separators=(",", ":")), file=sys.stderr)

                            status = event.get("status")
                            progress_percent = event.get("progress_percent")

                            if progress_percent is not None and not has_progress and not debug:
                                has_progress = True
                                progress_bar = tqdm(
                                    total=100,
                                    desc="Processing",
                                    unit="%",
                                    bar_format="{desc}: {percentage:3.0f}% |{bar}| {postfix}",
                                    file=sys.stderr,
                                )

                            if progress_bar:
                                envelope_state = event.get("envelope_state", "")
                                actor = event.get("actor", "")
                                progress_bar.n = int(progress_percent) if progress_percent else 0

                                postfix_parts = []
                                if actor:
                                    postfix_parts.append(actor)
                                if envelope_state:
                                    postfix_parts.append(envelope_state)
                                elif status:
                                    postfix_parts.append(status)

                                progress_bar.set_postfix_str(" | ".join(postfix_parts) if postfix_parts else "")
                                progress_bar.refresh()

                            if status in ["succeeded", "failed"]:
                                if progress_bar:
                                    progress_bar.n = 100
                                    progress_bar.refresh()
                                    progress_bar.close()
                                final_result = event
                                break

                        except json.JSONDecodeError:
                            print(f"[.] {data}", file=sys.stderr)

            if progress_bar and not progress_bar.disable:
                progress_bar.close()

            if final_result:
                return final_result

            status = self.get_status(envelope_id)
            return status

        except requests.exceptions.RequestException as e:
            if progress_bar:
                progress_bar.close()
            print(f"[-] Stream failed: {e}", file=sys.stderr)
            sys.exit(1)

    def _print_event(self, event: dict[str, Any]) -> None:
        """Pretty print an SSE event."""
        event_type = event.get("type", "unknown")
        if event_type == "progress":
            actor = event.get("actor", "?")
            step = event.get("step", 0)
            total = event.get("total", 0)
            print(f"[+] Progress: {actor} ({step}/{total})", file=sys.stderr)
        elif event_type == "completed":
            print(f"[+] Completed: {json.dumps(event.get('result', {}), indent=2)}", file=sys.stderr)
        elif event_type == "failed":
            print(f"[-] Failed: {event.get('error', 'unknown')}", file=sys.stderr)
        else:
            print(f"[.] {event_type}: {json.dumps(event, indent=2)}", file=sys.stderr)
