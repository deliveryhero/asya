"""
Error handling and formatting for Flow DSL compiler.

Provides rich, helpful error messages with source code context.
"""

import ast
from dataclasses import dataclass


@dataclass
class SourceLocation:
    """Location in source code."""

    line: int
    col: int
    source_file: str


@dataclass
class CompileError:
    """
    A single compilation error.

    Attributes:
        location: Where the error occurred
        message: Short error description
        explanation: Detailed explanation of why it's wrong
        fix_hint: Suggestion on how to fix
        code_context: Lines of code around the error
    """

    location: SourceLocation
    message: str
    explanation: str
    fix_hint: str | None = None
    code_context: list[tuple[int, str]] | None = None


class FlowCompileError(Exception):
    """
    Exception raised when flow compilation fails.

    Collects multiple errors and formats them with rich context.
    """

    def __init__(self, errors: list[CompileError], source_file: str, source_lines: list[str]):
        self.errors = errors
        self.source_file = source_file
        self.source_lines = source_lines
        super().__init__(self._format_errors())

    def _format_errors(self) -> str:
        """Format all errors with source context."""
        if not self.errors:
            return "Unknown compilation error"

        # Show max 5 errors, then "...and N more"
        errors_to_show = self.errors[:5]
        remaining = len(self.errors) - 5

        parts = []
        for i, error in enumerate(errors_to_show):
            if i > 0:
                parts.append("\n" + "─" * 60 + "\n")
            parts.append(self._format_error(error))

        if remaining > 0:
            parts.append(f"\n\n...and {remaining} more error{'s' if remaining > 1 else ''}.")
            parts.append("\nRun with --verbose to see all errors.")

        return "\n".join(parts)

    def _format_error(self, error: CompileError) -> str:
        """Format a single error with context."""
        parts = []

        if error.location:
            parts.append(f"Error compiling flow in {error.location.source_file}:\n")

            # Show source context
            if error.code_context:
                parts.append(self._format_code_context(error.code_context, error.location))
        else:
            parts.append(f"Error compiling flow in {self.source_file}:\n")

        # Error message
        parts.append(f"  {error.message}")

        # Explanation
        if error.explanation:
            parts.append(f"\n  {error.explanation}")

        # Fix hint
        if error.fix_hint:
            parts.append(f"\n  Fix: {error.fix_hint}")

        return "\n".join(parts)

    def _format_code_context(
        self, context: list[tuple[int, str]], location: SourceLocation, context_lines: int = 2
    ) -> str:
        """
        Format source code context around the error.

        Args:
            context: List of (line_num, line_text) tuples
            location: Error location
            context_lines: Number of lines to show before/after

        Returns:
            Formatted context with error indicator
        """
        parts = []
        parts.append(f"  Line {location.line}, column {location.col}:\n")

        for line_num, line_text in context:
            # Line number and content
            parts.append(f"    {line_num:>4} | {line_text}")

            # Add pointer for the error line
            if line_num == location.line:
                # Calculate pointer position
                # Add spaces for line number prefix: "    nnnn | "
                prefix_len = 4 + 5 + 2  # "    " + "nnnn " + "| "
                pointer = " " * (prefix_len + location.col) + "^" * max(1, min(len(line_text) - location.col, 10))
                parts.append(pointer)

        return "\n".join(parts)


def get_code_context(source_lines: list[str], lineno: int, context_lines: int = 2) -> list[tuple[int, str]]:
    """
    Extract code context around a line.

    Args:
        source_lines: All source lines
        lineno: Line number (1-indexed)
        context_lines: Number of lines before/after to include

    Returns:
        List of (line_num, line_text) tuples
    """
    start = max(0, lineno - context_lines - 1)
    end = min(len(source_lines), lineno + context_lines)

    context = []
    for i in range(start, end):
        line_num = i + 1
        line_text = source_lines[i].rstrip()
        context.append((line_num, line_text))

    return context


def create_error(
    message: str,
    node: ast.AST,
    source_file: str,
    source_lines: list[str],
    explanation: str = "",
    fix_hint: str | None = None,
) -> CompileError:
    """
    Create a CompileError from an AST node.

    Args:
        message: Short error message
        node: AST node where error occurred
        source_file: Source file path
        source_lines: Source file lines
        explanation: Detailed explanation
        fix_hint: Suggestion for fixing

    Returns:
        CompileError instance
    """
    location = SourceLocation(
        line=node.lineno,
        col=node.col_offset,
        source_file=source_file,
    )

    context = get_code_context(source_lines, node.lineno)

    return CompileError(
        location=location,
        message=message,
        explanation=explanation,
        fix_hint=fix_hint,
        code_context=context,
    )
