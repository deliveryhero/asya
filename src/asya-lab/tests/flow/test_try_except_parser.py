"""Unit tests for try/except parsing in the flow parser."""

import textwrap

import pytest
from asya_lab.flow.errors import FlowCompileError
from asya_lab.flow.parser import FlowParser, TryExcept


class TestTryExceptParsing:
    """try/except blocks are parsed into TryExcept operations."""

    def test_simple_try_except(self):
        source = textwrap.dedent("""
            @flow
            def my_flow(p: dict) -> dict:
                try:
                    p = handler(p)
                except ValueError:
                    p = error_handler(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        result = parser.parse()

        ops = result.operations
        assert len(ops) == 2  # TryExcept + Return
        te = ops[0]
        assert isinstance(te, TryExcept)
        assert len(te.body) == 1  # handler
        assert len(te.handlers) == 1
        assert te.handlers[0].error_types == ["ValueError"]
        assert len(te.handlers[0].body) == 1  # error_handler

    def test_try_except_with_mutation_in_handler(self):
        source = textwrap.dedent("""
            @flow
            def my_flow(p: dict) -> dict:
                try:
                    p = validate(p)
                except ValueError:
                    p["status"] = "invalid"
                    p = notify_rejection(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        result = parser.parse()
        te = result.operations[0]
        assert isinstance(te, TryExcept)
        assert len(te.handlers[0].body) == 2  # mutation + actor call

    def test_multiple_except_handlers(self):
        source = textwrap.dedent("""
            @flow
            def my_flow(p: dict) -> dict:
                try:
                    p = parse_input(p)
                except ValueError:
                    p = handle_validation(p)
                except TypeError:
                    p = handle_type(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        result = parser.parse()
        te = result.operations[0]
        assert isinstance(te, TryExcept)
        assert len(te.handlers) == 2
        assert te.handlers[0].error_types == ["ValueError"]
        assert te.handlers[1].error_types == ["TypeError"]

    def test_bare_except(self):
        source = textwrap.dedent("""
            @flow
            def my_flow(p: dict) -> dict:
                try:
                    p = handler(p)
                except:
                    p = fallback(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        result = parser.parse()
        te = result.operations[0]
        assert isinstance(te, TryExcept)
        assert te.handlers[0].error_types is None

    def test_try_except_finally(self):
        source = textwrap.dedent("""
            @flow
            def my_flow(p: dict) -> dict:
                try:
                    p = process(p)
                except RuntimeError:
                    p = handle_error(p)
                finally:
                    p = cleanup(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        result = parser.parse()
        te = result.operations[0]
        assert isinstance(te, TryExcept)
        assert len(te.finally_body) == 1  # cleanup

    def test_multiple_actors_in_try_body(self):
        source = textwrap.dedent("""
            @flow
            def my_flow(p: dict) -> dict:
                try:
                    p = validate(p)
                    p = process(p)
                except ValueError:
                    p = notify_rejection(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        result = parser.parse()
        te = result.operations[0]
        assert isinstance(te, TryExcept)
        assert len(te.body) == 2

    def test_tuple_exception_types(self):
        source = textwrap.dedent("""
            @flow
            def my_flow(p: dict) -> dict:
                try:
                    p = handler(p)
                except (ValueError, TypeError):
                    p = error_handler(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        result = parser.parse()
        te = result.operations[0]
        assert isinstance(te, TryExcept)
        assert te.handlers[0].error_types == ["ValueError", "TypeError"]

    def test_fqn_exception_type(self):
        source = textwrap.dedent("""
            @flow
            def my_flow(p: dict) -> dict:
                try:
                    p = handler(p)
                except openai.RateLimitError:
                    p = retry_handler(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        result = parser.parse()
        te = result.operations[0]
        assert isinstance(te, TryExcept)
        assert te.handlers[0].error_types == ["openai.RateLimitError"]

    def test_raise_in_except_body(self):
        source = textwrap.dedent("""
            @flow
            def my_flow(p: dict) -> dict:
                try:
                    p = handler(p)
                except ValueError:
                    p = log_error(p)
                    raise
                return p
        """)
        parser = FlowParser(source, "test.py")
        result = parser.parse()
        te = result.operations[0]
        assert isinstance(te, TryExcept)
        # raise becomes Return (terminal)
        from asya_lab.flow.parser import Return

        assert isinstance(te.handlers[0].body[-1], Return)

    def test_actors_collected_from_try_body(self):
        source = textwrap.dedent("""
            @flow
            def my_flow(p: dict) -> dict:
                try:
                    p = validate(p)
                    p = process(p)
                except ValueError:
                    p = notify_rejection(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        result = parser.parse()
        assert "validate" in result.actors
        assert "process" in result.actors
        assert "notify_rejection" in result.actors


class TestTryExceptRejection:
    """Cases that should still raise errors."""

    def test_try_without_except_rejected(self):
        source = textwrap.dedent("""
            @flow
            def my_flow(p: dict) -> dict:
                try:
                    p = handler(p)
                finally:
                    p["done"] = True
                return p
        """)
        parser = FlowParser(source, "test.py")
        with pytest.raises(FlowCompileError, match="try/finally without except"):
            parser.parse()

    def test_named_exception_rejected(self):
        source = textwrap.dedent("""
            @flow
            def my_flow(p: dict) -> dict:
                try:
                    p = handler(p)
                except ValueError as e:
                    p["error"] = str(e)
                return p
        """)
        parser = FlowParser(source, "test.py")
        with pytest.raises(FlowCompileError, match="naming the exception"):
            parser.parse()

    def test_try_else_rejected(self):
        source = textwrap.dedent("""
            @flow
            def my_flow(p: dict) -> dict:
                try:
                    p = handler(p)
                except ValueError:
                    p = error_handler(p)
                else:
                    p["ok"] = True
                return p
        """)
        parser = FlowParser(source, "test.py")
        with pytest.raises(FlowCompileError, match="'else' clause"):
            parser.parse()

    def test_raise_outside_except_rejected(self):
        source = textwrap.dedent("""
            @flow
            def my_flow(p: dict) -> dict:
                raise RuntimeError("boom")
        """)
        parser = FlowParser(source, "test.py")
        with pytest.raises(FlowCompileError, match="'raise' is only supported inside except"):
            parser.parse()
