#!/usr/bin/env python3
"""
CLI for Flow DSL compiler.

Commands:
    compile    - Compile flow to routers
    validate   - Validate flow without compiling

Usage:
    asya flow compile <flow_file.py> [options]
    asya flow validate <flow_file.py> [options]
"""

import argparse
import sys
from pathlib import Path

from asya_lab.flow import FlowCompileError, FlowCompiler
from asya_lab.flow.grouper import DEFAULT_MAX_LOOP_ITERATIONS


def _check_positive_int(value: str) -> int:
    """Argparse type checker for positive integers."""
    ivalue = int(value)
    if ivalue <= 0:
        raise argparse.ArgumentTypeError(f"must be a positive integer, but got {value}")
    return ivalue


def cmd_compile(args):
    """Compile flow file."""
    try:
        if not args.output_dir:
            print("[-] Error: --output-dir is required", file=sys.stderr)
            sys.exit(1)

        compiler = FlowCompiler(
            verbose=args.verbose,
            max_iterations=args.max_iterations,
        )

        compiled_file = compiler.compile_file(args.flow_file, args.output_dir, overwrite=args.overwrite)
        print(f"[+] Successfully compiled flow to: {compiled_file}")

        actor = compiler.single_actor_name
        if actor is not None:
            print("[+] Single-actor flow detected: no router actor needed")
            print(f"[+] Apply these labels to actor '{actor}':")
            print(f"[+]   asya.sh/flow: {compiler.flow_name}")
            print("[+]   asya.sh/flow-role: entrypoint")

        if args.plot:
            try:
                dot_file, png_path = compiler.generate_plot(args.output_dir, plot_width=args.plot_width)
                print(f"[+] Generated graphviz dot file: {dot_file}")
                if png_path:
                    print(f"[+] Generated graphviz png plot: {png_path}")
            except ImportError as e:
                print(f"[!] Warning: {e}", file=sys.stderr)
            except RuntimeError as e:
                print(f"[!] Warning: {e}", file=sys.stderr)
            except Exception as e:
                print(f"[!] Warning: Failed to generate plot: {e}", file=sys.stderr)

        warnings = compiler.get_warnings()
        if warnings:
            print("\nWarnings:", file=sys.stderr)
            for warning in warnings:
                print(f"\n{warning}", file=sys.stderr)

    except FlowCompileError as e:
        print(f"[-] Compilation failed for {args.flow_file}\n", file=sys.stderr)
        print(str(e), file=sys.stderr)
        sys.exit(1)
    except (FileNotFoundError, ValueError) as e:
        print(f"[-] {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"[-] Unexpected error: {e}", file=sys.stderr)
        if args.verbose:
            import traceback

            traceback.print_exc()
        sys.exit(1)


def cmd_validate(args):
    """Validate flow file."""
    try:
        compiler = FlowCompiler(
            verbose=args.verbose,
        )

        source_path = Path(args.flow_file)
        if not source_path.exists():
            print(f"[-] Source file not found: {args.flow_file}", file=sys.stderr)
            sys.exit(1)

        source_code = source_path.read_text()
        compiler.validate(source_code, str(source_path))

        print(f"[+] Flow is valid: {args.flow_file}")

        # Show warnings if any
        warnings = compiler.get_warnings()
        if warnings:
            print("\nWarnings:", file=sys.stderr)
            for warning in warnings:
                print(f"\n{warning}", file=sys.stderr)

    except FlowCompileError as e:
        print("[-] Validation failed:\n", file=sys.stderr)
        print(str(e), file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"[-] Unexpected error: {e}", file=sys.stderr)
        if args.verbose:
            import traceback

            traceback.print_exc()
        sys.exit(1)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="asya flow",
        description="Flow DSL compiler for Asya",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    subparsers = parser.add_subparsers(dest="command", required=True, help="Command to run")

    # Compile command
    compile_parser = subparsers.add_parser("compile", help="Compile flow to routers")
    compile_parser.add_argument("flow_file", help="Flow source file (.py)")
    compile_parser.add_argument(
        "--output-dir",
        "-o",
        required=True,
        help="Output directory for compiled files (must not exist or be empty)",
    )
    compile_parser.add_argument(
        "--max-iterations",
        type=_check_positive_int,
        default=DEFAULT_MAX_LOOP_ITERATIONS,
        help=f"Maximum iterations for while-True loops before raising RuntimeError (default: {DEFAULT_MAX_LOOP_ITERATIONS}). "
        "Can be overridden at deploy time via ASYA_MAX_LOOP_ITERATIONS env var on router actors.",
    )
    compile_parser.add_argument(
        "--disable-infinite-loop-check",
        action="store_true",
        help="Disable infinite loop detection",
    )
    compile_parser.add_argument("--verbose", "-v", action="store_true", help="Show verbose output")
    compile_parser.add_argument(
        "--plot",
        action="store_true",
        help="Generate flow diagram in DOT format and PNG (requires graphviz for PNG)",
    )
    compile_parser.add_argument(
        "--plot-width",
        type=int,
        default=50,
        help="Maximum width for plot node labels (default: 50 characters)",
    )
    compile_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing files in output directory",
    )
    compile_parser.set_defaults(func=cmd_compile)

    # Validate command
    validate_parser = subparsers.add_parser("validate", help="Validate flow without compiling")
    validate_parser.add_argument("flow_file", help="Flow source file (.py)")
    validate_parser.add_argument(
        "--disable-infinite-loop-check",
        action="store_true",
        help="Disable infinite loop detection",
    )
    validate_parser.add_argument("--verbose", "-v", action="store_true", help="Show verbose output")
    validate_parser.set_defaults(func=cmd_validate)

    args = parser.parse_args(argv)

    # Run command
    args.func(args)


if __name__ == "__main__":
    main()
