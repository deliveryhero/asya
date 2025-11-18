#!/usr/bin/env python3
"""
Simple CLI for calling tools on asya gateway MCP server.
For debugging and manual tool invocation without AI.

Usage:
    asya-mcp [--url URL] [--no-stream] [--debug] <command>

Commands:
    list                                           # List available tools
    show <tool-name>                               # Show tool configuration
    call <tool-name> [json-args]                   # Call a tool (streams results by default)
    call <tool-name> --param=value                 # Call with --param=value flags
    status <envelope-id>                           # Check envelope status
    stream <envelope-id>                           # Stream envelope updates

Global Options:
    --url URL                                      # Gateway URL (env: ASYA_CLI_MCP_URL, default: http://localhost:8089)
    --no-stream, --no_stream                       # Disable streaming, return envelope ID immediately
    --debug                                        # Print SSE events as JSON (env: ASYA_CLI_MCP_DEBUG)

Examples:
    export ASYA_CLI_MCP_URL=http://localhost:8011
    asya-mcp list
    asya-mcp show echo
    asya-mcp call my_tool                          # Streams results by default
    asya-mcp call echo '{"message": "hello"}'      # With JSON arguments
    asya-mcp call echo --message=hello             # With --param flags
    asya-mcp call echo --message hello
    asya-mcp --no-stream call long-task --data=x   # Return envelope ID immediately
    asya-mcp --debug call test_timeout --sleep_seconds 5
    asya-mcp --url http://other:8080 list
    asya-mcp status abc-123
    asya-mcp stream abc-123
"""

import argparse
import json
import os
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
        if not content:
            return None

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

                                # Include actor name in postfix if available
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


def main():
    default_url = os.getenv("ASYA_CLI_MCP_URL", "http://localhost:8089")
    default_debug = os.getenv("ASYA_CLI_MCP_DEBUG", "").lower() in ["1", "true", "yes"]

    parser = argparse.ArgumentParser(
        description="Simple CLI for asya gateway MCP server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Global options (before command)
    parser.add_argument(
        "--url",
        default=default_url,
        help=f"Gateway URL (default: {default_url}, set via ASYA_CLI_MCP_URL)",
    )
    parser.add_argument(
        "--no-stream",
        "--no_stream",
        action="store_true",
        default=False,
        help="Disable streaming and return envelope ID immediately (streaming is enabled by default)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=default_debug,
        help=f"Print each SSE event as one-line JSON to stderr (default: {default_debug}, set via ASYA_CLI_MCP_DEBUG)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="List available tools")

    show_parser = subparsers.add_parser("show", help="Show detailed tool configuration")
    show_parser.add_argument("tool", help="Tool name to show")

    call_parser = subparsers.add_parser("call", help="Call a tool")
    call_parser.add_argument("tool", help="Tool name")
    call_parser.add_argument("params", nargs=argparse.REMAINDER, help="Tool parameters as JSON or --param flags")

    status_parser = subparsers.add_parser("status", help="Get envelope status")
    status_parser.add_argument("envelope_id", help="Envelope ID")

    stream_parser = subparsers.add_parser("stream", help="Stream envelope updates")
    stream_parser.add_argument("envelope_id", help="Envelope ID")

    args = parser.parse_args()

    client = AsyaGatewayClient(base_url=args.url)

    if args.command == "list":
        import yaml  # type: ignore[import-untyped]

        result = client.list_tools()
        tools = result.get("result", {}).get("tools", [])
        if not tools:
            print("[!] No tools available", file=sys.stderr)
            return

        tools_data = [client._tool_to_dict(tool, show_details=False) for tool in tools]
        print(yaml.dump(tools_data, default_flow_style=False, sort_keys=False))

    elif args.command == "show":
        import yaml

        tool = client.show_tool(args.tool)
        if not tool:
            print(f"[-] Tool '{args.tool}' not found", file=sys.stderr)
            sys.exit(1)

        tool_data = client._tool_to_dict(tool, show_details=True)
        print(yaml.dump(tool_data, default_flow_style=False, sort_keys=False))

    elif args.command == "call":
        # Parse parameters from args.params (captured by REMAINDER)
        params = getattr(args, "params", [])

        # Check if first param is JSON string
        if params and not params[0].startswith("--"):
            json_str = params[0]
            try:
                arguments = json.loads(json_str)
            except json.JSONDecodeError as e:
                print(f"[-] Invalid JSON arguments: {e}", file=sys.stderr)
                print(
                    f'[-] Hint: Arguments must be valid JSON. Example: \'{{"{args.tool}_arg": "value"}}\'',
                    file=sys.stderr,
                )
                print(f"[-] You provided: {json_str}", file=sys.stderr)
                sys.exit(1)
        else:
            # Use argparse to parse --param flags dynamically
            # Create a new parser that accepts any --param arguments
            param_parser = argparse.ArgumentParser(add_help=False)

            # First pass: discover all --param names
            seen_params = set()
            for param in params:
                if param.startswith("--"):
                    param_name = param[2:].split("=")[0] if "=" in param else param[2:]
                    if param_name not in seen_params:
                        seen_params.add(param_name)
                        # Add as optional argument that can take a value or be a flag
                        param_parser.add_argument(f"--{param_name}", nargs="?", const=True)

            # Parse the params
            try:
                parsed = param_parser.parse_args(params)
            except SystemExit:
                print("[-] Failed to parse tool parameters", file=sys.stderr)
                sys.exit(1)

            # Convert to dict with type conversion
            arguments = {}
            for param_name in seen_params:
                value = getattr(parsed, param_name, None)
                if value is not None:
                    if isinstance(value, bool):
                        arguments[param_name] = value
                    elif isinstance(value, str):
                        # Type conversion
                        if value.lower() in ["true", "false"]:
                            arguments[param_name] = value.lower() == "true"
                        else:
                            try:
                                if "." in value:
                                    arguments[param_name] = float(value)
                                else:
                                    arguments[param_name] = int(value)
                            except ValueError:
                                arguments[param_name] = value
                    else:
                        arguments[param_name] = value

        if args.debug:
            print(f"[.] Calling tool: {args.tool}", file=sys.stderr)
            print(f"[.] Arguments: {json.dumps(arguments)}", file=sys.stderr)

        result = client.call_tool(args.tool, arguments, stream=not args.no_stream, debug=args.debug)
        print(json.dumps(result, indent=2))

    elif args.command == "status":
        status = client.get_status(args.envelope_id)
        print(json.dumps(status, indent=2))

    elif args.command == "stream":
        client.stream_updates(args.envelope_id)


if __name__ == "__main__":
    main()
