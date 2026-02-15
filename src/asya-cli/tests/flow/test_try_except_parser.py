"""Unit tests for try-except parsing in the flow parser."""

import textwrap

import pytest
from asya_cli.flow.errors import FlowCompileError
from asya_cli.flow.ir import ActorCall, ExceptHandler, Mutation, Raise, Return, TryExcept
from asya_cli.flow.parser import FlowParser


class TestTryExceptParsing:
    """Test parsing of valid try-except constructs."""

    def test_simple_try_except(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                try:
                    p = handler(p)
                except ValueError:
                    p["error"] = "validation_failed"
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert len(ops) == 2
        assert isinstance(ops[0], TryExcept)
        assert isinstance(ops[1], Return)

        te = ops[0]
        assert len(te.body) == 1
        assert isinstance(te.body[0], ActorCall)
        assert te.body[0].name == "handler"

        assert len(te.handlers) == 1
        assert isinstance(te.handlers[0], ExceptHandler)
        assert te.handlers[0].error_types == ["ValueError"]
        assert len(te.handlers[0].body) == 1
        assert isinstance(te.handlers[0].body[0], Mutation)

        assert len(te.finally_body) == 0

    def test_try_except_finally(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                try:
                    p = handler(p)
                except ValueError:
                    p["error"] = "validation_failed"
                finally:
                    p["done"] = True
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert len(ops) == 2
        assert isinstance(ops[0], TryExcept)

        te = ops[0]
        assert len(te.body) == 1
        assert isinstance(te.body[0], ActorCall)

        assert len(te.handlers) == 1
        assert te.handlers[0].error_types == ["ValueError"]

        assert len(te.finally_body) == 1
        assert isinstance(te.finally_body[0], Mutation)

    def test_multiple_except_handlers(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                try:
                    p = handler(p)
                except ValueError:
                    p["error"] = "value_error"
                except KeyError:
                    p["error"] = "key_error"
                except RuntimeError:
                    p["error"] = "runtime_error"
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert isinstance(ops[0], TryExcept)
        te = ops[0]
        assert len(te.handlers) == 3
        assert te.handlers[0].error_types == ["ValueError"]
        assert te.handlers[1].error_types == ["KeyError"]
        assert te.handlers[2].error_types == ["RuntimeError"]

    def test_bare_except(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                try:
                    p = handler(p)
                except:
                    p["error"] = "unknown"
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert isinstance(ops[0], TryExcept)
        te = ops[0]
        assert len(te.handlers) == 1
        assert te.handlers[0].error_types is None
        assert len(te.handlers[0].body) == 1
        assert isinstance(te.handlers[0].body[0], Mutation)

    def test_tuple_exception_types(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                try:
                    p = handler(p)
                except (ValueError, TypeError):
                    p["error"] = "type_or_value"
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert isinstance(ops[0], TryExcept)
        te = ops[0]
        assert len(te.handlers) == 1
        assert te.handlers[0].error_types == ["ValueError", "TypeError"]

    def test_try_with_mutations_in_handler(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                try:
                    p = handler(p)
                except ValueError:
                    p["error"] = "failed"
                    p["status"] = "error"
                    p["retries"] += 1
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert isinstance(ops[0], TryExcept)
        te = ops[0]
        assert len(te.handlers[0].body) == 3
        assert all(isinstance(op, Mutation) for op in te.handlers[0].body)

    def test_try_with_actor_in_handler(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                try:
                    p = risky_handler(p)
                except ValueError:
                    p = fallback_handler(p)
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert isinstance(ops[0], TryExcept)
        te = ops[0]
        assert len(te.body) == 1
        assert isinstance(te.body[0], ActorCall)
        assert te.body[0].name == "risky_handler"

        assert len(te.handlers[0].body) == 1
        assert isinstance(te.handlers[0].body[0], ActorCall)
        assert te.handlers[0].body[0].name == "fallback_handler"

    def test_try_with_multiple_body_statements(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                try:
                    p = handler_a(p)
                    p = handler_b(p)
                    p = handler_c(p)
                except ValueError:
                    p["error"] = "failed"
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert isinstance(ops[0], TryExcept)
        te = ops[0]
        assert len(te.body) == 3
        assert all(isinstance(op, ActorCall) for op in te.body)
        assert isinstance(te.body[0], ActorCall) and te.body[0].name == "handler_a"
        assert isinstance(te.body[1], ActorCall) and te.body[1].name == "handler_b"
        assert isinstance(te.body[2], ActorCall) and te.body[2].name == "handler_c"

    def test_try_except_preserves_lineno(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                try:
                    p = handler(p)
                except ValueError:
                    p["error"] = "failed"
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert isinstance(ops[0], TryExcept)
        te = ops[0]
        assert te.lineno == 3
        assert te.body[0].lineno == 4
        assert te.handlers[0].lineno == 5
        assert te.handlers[0].body[0].lineno == 6


class TestRaiseParsing:
    """Test parsing of raise statements."""

    def test_raise_in_except_body(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                try:
                    p = handler(p)
                except ValueError:
                    p["error"] = "failed"
                    raise
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert isinstance(ops[0], TryExcept)
        te = ops[0]
        assert len(te.handlers[0].body) == 2
        assert isinstance(te.handlers[0].body[0], Mutation)
        assert isinstance(te.handlers[0].body[1], Raise)

    def test_raise_in_except_with_condition(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                try:
                    p = handler(p)
                except ValueError:
                    if p["critical"]:
                        raise
                    p["error"] = "handled"
                return p
        """)
        parser = FlowParser(source, "test.py")
        _, ops = parser.parse()

        assert isinstance(ops[0], TryExcept)
        te = ops[0]
        handler = te.handlers[0]
        assert len(handler.body) == 2

        from asya_cli.flow.ir import Condition

        assert isinstance(handler.body[0], Condition)
        cond = handler.body[0]
        assert len(cond.true_branch) == 1
        assert isinstance(cond.true_branch[0], Raise)

        assert isinstance(handler.body[1], Mutation)


class TestTryExceptErrors:
    """Test rejection of invalid try-except constructs."""

    def test_nested_try_rejected(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                try:
                    try:
                        p = handler(p)
                    except ValueError:
                        p["error"] = "inner"
                except RuntimeError:
                    p["error"] = "outer"
                return p
        """)
        parser = FlowParser(source, "test.py")
        with pytest.raises(FlowCompileError, match="Nested try-except"):
            parser.parse()

    def test_try_else_rejected(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                try:
                    p = handler(p)
                except ValueError:
                    p["error"] = "failed"
                else:
                    p["status"] = "ok"
                return p
        """)
        parser = FlowParser(source, "test.py")
        with pytest.raises(FlowCompileError, match="'else' clause on 'try'"):
            parser.parse()

    def test_except_as_binding_rejected(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                try:
                    p = handler(p)
                except ValueError as e:
                    p["error"] = "failed"
                return p
        """)
        parser = FlowParser(source, "test.py")
        with pytest.raises(FlowCompileError, match="binding"):
            parser.parse()

    def test_raise_outside_except_rejected(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                raise
                return p
        """)
        parser = FlowParser(source, "test.py")
        with pytest.raises(FlowCompileError, match="'raise' outside except"):
            parser.parse()

    def test_raise_with_args_rejected(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                try:
                    p = handler(p)
                except ValueError:
                    raise ValueError("msg")
                return p
        """)
        parser = FlowParser(source, "test.py")
        with pytest.raises(FlowCompileError, match="with arguments"):
            parser.parse()

    def test_try_without_except_rejected(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                try:
                    p = handler(p)
                finally:
                    p["done"] = True
                return p
        """)
        parser = FlowParser(source, "test.py")
        with pytest.raises(FlowCompileError, match="at least one 'except'"):
            parser.parse()

    def test_raise_in_try_body_rejected(self):
        source = textwrap.dedent("""
            def flow(p: dict) -> dict:
                try:
                    p = handler(p)
                    raise
                except ValueError:
                    p["error"] = "failed"
                return p
        """)
        parser = FlowParser(source, "test.py")
        with pytest.raises(FlowCompileError, match="'raise' outside except"):
            parser.parse()
