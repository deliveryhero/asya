"""Unit tests for try-except rejection in the flow parser."""

import textwrap

import pytest
from asya_lab.flow.errors import FlowCompileError
from asya_lab.flow.parser import FlowParser


class TestTryExceptRejection:
    """try/except is not supported and must raise FlowCompileError."""

    def test_simple_try_except_rejected(self):
        source = textwrap.dedent("""
            @flow
            def flow(p: dict) -> dict:
                try:
                    p = handler(p)
                except ValueError:
                    p["error"] = "failed"
                return p
        """)
        parser = FlowParser(source, "test.py")
        with pytest.raises(FlowCompileError, match="try/except is not supported"):
            parser.parse()

    def test_try_except_finally_rejected(self):
        source = textwrap.dedent("""
            @flow
            def flow(p: dict) -> dict:
                try:
                    p = handler(p)
                except ValueError:
                    p["error"] = "failed"
                finally:
                    p["done"] = True
                return p
        """)
        parser = FlowParser(source, "test.py")
        with pytest.raises(FlowCompileError, match="try/except is not supported"):
            parser.parse()

    def test_bare_except_rejected(self):
        source = textwrap.dedent("""
            @flow
            def flow(p: dict) -> dict:
                try:
                    p = handler(p)
                except:
                    p["error"] = "unknown"
                return p
        """)
        parser = FlowParser(source, "test.py")
        with pytest.raises(FlowCompileError, match="try/except is not supported"):
            parser.parse()

    def test_try_without_except_rejected(self):
        source = textwrap.dedent("""
            @flow
            def flow(p: dict) -> dict:
                try:
                    p = handler(p)
                finally:
                    p["done"] = True
                return p
        """)
        parser = FlowParser(source, "test.py")
        with pytest.raises(FlowCompileError, match="try/except is not supported"):
            parser.parse()
