#!/usr/bin/env python3
"""
MCP subcommand handlers for asya CLI.

Usage:
    asya mcp [--url URL] [--no-stream] [--debug] <command>

Commands:
    list                                           # List available tools
    show <tool-name>                               # Show tool configuration
    call <tool-name> [json-args]                   # Call a tool (streams results by default)
    call <tool-name> --param=value                 # Call with --param=value flags
    status <envelope-id>                           # Check envelope status
    stream <envelope-id>                           # Stream envelope updates
    port-forward [options]                         # Start kubectl port-forward

Global Options:
    --url URL                                      # Gateway URL (env: ASYA_CLI_MCP_URL, default: http://localhost:8089)
    --no-stream, --no_stream                       # Disable streaming, return envelope ID immediately
    --debug                                        # Print SSE events as JSON (env: ASYA_CLI_MCP_DEBUG)

Examples:
    export ASYA_CLI_MCP_URL=http://localhost:8011
    asya mcp list
    asya mcp show echo
    asya mcp call my_tool                          # Streams results by default
    asya mcp call echo '{"message": "hello"}'      # With JSON arguments
    asya mcp call echo --message=hello             # With --param flags
    asya mcp call echo --message hello
    asya mcp --no-stream call long-task --data=x   # Return envelope ID immediately
    asya mcp --debug call test_timeout --sleep_seconds 5
    asya mcp --url http://other:8080 list
    asya mcp status abc-123
    asya mcp stream abc-123
    asya mcp port-forward                          # Start port-forward
    asya mcp port-forward --namespace my-ns        # Custom namespace
"""

import argparse
import json
import os
import sys

from asya_cli.mcp.client import AsyaGatewayClient


def main() -> None:
    default_url = os.getenv("ASYA_CLI_MCP_URL", "http://localhost:8089")
    default_debug = os.getenv("ASYA_CLI_MCP_DEBUG", "").lower() in ["1", "true", "yes"]

    parser = argparse.ArgumentParser(
        prog="asya mcp",
        description="MCP gateway tools for asya CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

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

    pf_parser = subparsers.add_parser("port-forward", help="Start kubectl port-forward to gateway")
    pf_parser.add_argument("--namespace", "-n", default="asya-e2e", help="Kubernetes namespace (default: asya-e2e)")
    pf_parser.add_argument("--deployment", "-d", default="asya-gateway", help="Deployment name (default: asya-gateway)")
    pf_parser.add_argument("--port", "-p", type=int, default=8080, help="Target port (default: 8080)")
    pf_parser.add_argument(
        "--local-port", "-l", type=int, default=None, help="Local port (default: auto-detect free port)"
    )
    pf_parser.add_argument(
        "--check-health",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Verify gateway health endpoint (default: enabled)",
    )
    pf_parser.add_argument(
        "--keep-alive",
        action="store_true",
        default=False,
        help="Keep port-forward running until interrupted (default: false)",
    )

    args = parser.parse_args()

    if args.command == "port-forward":
        from asya_cli.mcp.port_forward import run_port_forward

        run_port_forward(
            namespace=args.namespace,
            deployment=args.deployment,
            remote_port=args.port,
            local_port=args.local_port,
            check_health_enabled=args.check_health,
            keep_alive=args.keep_alive,
        )
        return

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
        params = getattr(args, "params", [])

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
            param_parser = argparse.ArgumentParser(add_help=False)

            seen_params = set()
            for param in params:
                if param.startswith("--"):
                    param_name = param[2:].split("=")[0] if "=" in param else param[2:]
                    if param_name not in seen_params:
                        seen_params.add(param_name)
                        param_parser.add_argument(f"--{param_name}", nargs="?", const=True)

            try:
                parsed = param_parser.parse_args(params)
            except SystemExit:
                print("[-] Failed to parse tool parameters", file=sys.stderr)
                sys.exit(1)

            arguments = {}
            for param_name in seen_params:
                value = getattr(parsed, param_name, None)
                if value is not None:
                    if isinstance(value, bool):
                        arguments[param_name] = value
                    elif isinstance(value, str):
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
