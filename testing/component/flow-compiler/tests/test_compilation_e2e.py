"""End-to-end compilation tests for flow compiler."""

import textwrap

import pytest

from asya_lab.flow import FlowCompiler
from asya_lab.flow.errors import FlowCompileError


class TestErrorCases:
    """Test compilation error handling."""

    def test_invalid_syntax(self):
        source = "def flow(p: dict) -> dict\n    return p"

        compiler = FlowCompiler()
        with pytest.raises(FlowCompileError, match="Syntax error"):
            compiler.compile(source, "test.py")

    def test_no_flow_function(self):
        source = textwrap.dedent("""
            def helper(x: int) -> int:
                return x
        """)

        compiler = FlowCompiler()
        with pytest.raises(FlowCompileError, match="No @flow function found"):
            compiler.compile(source, "test.py")

    def test_invalid_handler_call(self):
        source = textwrap.dedent("""
            @flow
            def flow(p: dict) -> dict:
                p = handler()
                return p
        """)

        compiler = FlowCompiler()
        with pytest.raises(FlowCompileError, match="must have exactly one argument"):
            compiler.compile(source, "test.py")


class TestCodeGeneration:
    """Test that compilation produces valid executable code."""

    def test_generated_code_is_valid_python(self):
        source = textwrap.dedent("""
            @flow
            def flow(p: dict) -> dict:
                p = handler(p)
                return p

            def handler(p: dict) -> dict:
                return p
        """)

        compiler = FlowCompiler()
        code = compiler.compile(source, "test.py")

        try:
            compile(code, "test.py", "exec")
        except SyntaxError as e:
            pytest.fail(f"Generated code has syntax errors: {e}")

    def test_generated_code_contains_all_functions(self):
        source = textwrap.dedent("""
            @flow
            def flow(p: dict) -> dict:
                p = handler_a(p)
                p = handler_b(p)
                return p

            def handler_a(p: dict) -> dict:
                return p
            def handler_b(p: dict) -> dict:
                return p
        """)

        compiler = FlowCompiler()
        code = compiler.compile(source, "test.py")

        assert "def start_flow" in code
        assert "def resolve" in code
