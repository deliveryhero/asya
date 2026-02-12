"""Unit tests for try-except code generation."""

import ast
import textwrap

import pytest
from asya_cli.flow.codegen import CodeGenerator
from asya_cli.flow.grouper import OperationGrouper
from asya_cli.flow.parser import FlowParser


def _compile(source: str) -> str:
    """Parse, group, and generate code from flow source."""
    source = textwrap.dedent(source)
    parser = FlowParser(source, "test.py")
    flow_name, ops = parser.parse()
    grouper = OperationGrouper(flow_name, ops)
    routers = grouper.group()
    codegen = CodeGenerator(flow_name, routers, "test.py")
    return codegen.generate()


class TestTryExceptCodeGenValidity:
    """Generated code from try-except flows is valid Python."""

    def test_simple_try_except_generates_valid_python(self):
        source = """\
        def flow(p: dict) -> dict:
            try:
                p = risky_handler(p)
            except ValueError:
                p = fallback_handler(p)
            return p
        """
        code = _compile(source)
        try:
            ast.parse(code)
        except SyntaxError as e:
            pytest.fail(f"Generated code is not valid Python: {e}")

    def test_try_except_finally_generates_valid_python(self):
        source = """\
        def flow(p: dict) -> dict:
            try:
                p = risky_handler(p)
            except ValueError:
                p = fallback_handler(p)
            finally:
                p = cleanup_handler(p)
            return p
        """
        code = _compile(source)
        try:
            ast.parse(code)
        except SyntaxError as e:
            pytest.fail(f"Generated code is not valid Python: {e}")

    def test_multiple_handlers_generates_valid_python(self):
        source = """\
        def flow(p: dict) -> dict:
            try:
                p = risky_handler(p)
            except ValueError:
                p = value_handler(p)
            except TypeError:
                p = type_handler(p)
            except RuntimeError:
                p = runtime_handler(p)
            return p
        """
        code = _compile(source)
        try:
            ast.parse(code)
        except SyntaxError as e:
            pytest.fail(f"Generated code is not valid Python: {e}")

    def test_bare_except_generates_valid_python(self):
        source = """\
        def flow(p: dict) -> dict:
            try:
                p = risky_handler(p)
            except:
                p = catch_all_handler(p)
            return p
        """
        code = _compile(source)
        try:
            ast.parse(code)
        except SyntaxError as e:
            pytest.fail(f"Generated code is not valid Python: {e}")


class TestTryEnterCodeGen:
    """Test try_enter router code generation."""

    def test_try_enter_sets_on_error_header(self):
        source = """\
        def flow(p: dict) -> dict:
            try:
                p = risky_handler(p)
            except ValueError:
                p = fallback_handler(p)
            return p
        """
        code = _compile(source)

        assert "message.setdefault('headers', {})" in code
        assert "['_on_error']" in code

    def test_try_enter_uses_resolve(self):
        source = """\
        def flow(p: dict) -> dict:
            try:
                p = risky_handler(p)
            except ValueError:
                p = fallback_handler(p)
            return p
        """
        code = _compile(source)

        # The try_enter router should resolve the except_dispatch name
        assert 'resolve("' in code
        # Specifically, _on_error should point to the except_dispatch router
        assert "except_dispatch" in code


class TestTryExitCodeGen:
    """Test try_exit router code generation."""

    def test_try_exit_clears_on_error(self):
        source = """\
        def flow(p: dict) -> dict:
            try:
                p = risky_handler(p)
            except ValueError:
                p = fallback_handler(p)
            return p
        """
        code = _compile(source)

        assert ".pop('_on_error'" in code


class TestExceptDispatchCodeGen:
    """Test except_dispatch router code generation."""

    def test_except_dispatch_checks_error_type(self):
        source = """\
        def flow(p: dict) -> dict:
            try:
                p = risky_handler(p)
            except ValueError:
                p = fallback_handler(p)
            return p
        """
        code = _compile(source)

        assert "_error_type" in code
        assert "_error_mro" in code
        assert "_all_types" in code

    def test_except_dispatch_typed_handler_checks_in_all_types(self):
        source = """\
        def flow(p: dict) -> dict:
            try:
                p = risky_handler(p)
            except ValueError:
                p = fallback_handler(p)
            return p
        """
        code = _compile(source)

        assert '"ValueError" in _all_types' in code

    def test_except_dispatch_bare_except_uses_if_true(self):
        source = """\
        def flow(p: dict) -> dict:
            try:
                p = risky_handler(p)
            except:
                p = catch_all_handler(p)
            return p
        """
        code = _compile(source)

        assert "if True:" in code

    def test_except_dispatch_clears_error_on_match(self):
        source = """\
        def flow(p: dict) -> dict:
            try:
                p = risky_handler(p)
            except ValueError:
                p = fallback_handler(p)
            return p
        """
        code = _compile(source)

        assert "pop('error'" in code


class TestReraiseCodeGen:
    """Test reraise router code generation."""

    def test_reraise_raises_runtime_error(self):
        source = """\
        def flow(p: dict) -> dict:
            try:
                p = risky_handler(p)
            except ValueError:
                p = fallback_handler(p)
            return p
        """
        code = _compile(source)

        assert "raise RuntimeError" in code
