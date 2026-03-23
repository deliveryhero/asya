"""Unit tests for try/except code generation."""

import textwrap

from asya_lab.flow.codegen import CodeGenerator
from asya_lab.flow.parser import FlowParser


def _compile(source: str) -> tuple[str, CodeGenerator]:
    parser = FlowParser(textwrap.dedent(source), "test.py")
    result = parser.parse()
    codegen = CodeGenerator(result, "test.py")
    code = codegen.generate()
    return code, codegen


class TestTryExceptCodegen:
    def test_simple_try_except_generates_except_router(self):
        code, codegen = _compile("""
            @flow
            def my_flow(p: dict) -> dict:
                try:
                    p = validate(p)
                except ValueError:
                    p = notify_rejection(p)
                return p
        """)
        # Should contain an except router
        assert "except" in code
        assert "notify_rejection" in code
        assert "validate" in code

        meta = codegen.get_meta()
        # validate should have retry rules
        assert meta.actor_retry_rules is not None
        assert "validate" in meta.actor_retry_rules
        rules = meta.actor_retry_rules["validate"]
        assert len(rules) == 1
        assert rules[0].error_types == ["ValueError"]
        assert rules[0].policy_name == "except_valueerror"

    def test_multiple_handlers_generate_multiple_routers(self):
        code, codegen = _compile("""
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
        meta = codegen.get_meta()
        assert meta.actor_retry_rules is not None
        assert "parse_input" in meta.actor_retry_rules
        rules = meta.actor_retry_rules["parse_input"]
        assert len(rules) == 2
        assert rules[0].error_types == ["ValueError"]
        assert rules[1].error_types == ["TypeError"]

    def test_multiple_actors_in_try_body_all_get_rules(self):
        code, codegen = _compile("""
            @flow
            def my_flow(p: dict) -> dict:
                try:
                    p = validate(p)
                    p = process(p)
                except ValueError:
                    p = notify_rejection(p)
                return p
        """)
        meta = codegen.get_meta()
        assert meta.actor_retry_rules is not None
        assert "validate" in meta.actor_retry_rules
        assert "process" in meta.actor_retry_rules
        assert len(meta.actor_retry_rules["validate"]) == 1
        assert len(meta.actor_retry_rules["process"]) == 1

    def test_bare_except_generates_default_rule(self):
        code, codegen = _compile("""
            @flow
            def my_flow(p: dict) -> dict:
                try:
                    p = handler(p)
                except:
                    p = fallback(p)
                return p
        """)
        meta = codegen.get_meta()
        assert meta.actor_retry_rules is not None
        rules = meta.actor_retry_rules["handler"]
        assert len(rules) == 1
        assert rules[0].error_types is None  # bare except

    def test_finally_actors_in_success_path(self):
        code, codegen = _compile("""
            @flow
            def my_flow(p: dict) -> dict:
                try:
                    p = process(p)
                except RuntimeError:
                    p = handle_error(p)
                finally:
                    p = cleanup(p)
                p = finalize(p)
                return p
        """)
        # cleanup should appear in the generated code
        assert "cleanup" in code
        assert "finalize" in code
        # All handlers should be in the meta
        meta = codegen.get_meta()
        assert "process" in meta.all_handler_names
        assert "cleanup" in meta.all_handler_names
        assert "finalize" in meta.all_handler_names
        assert "handle_error" in meta.all_handler_names

    def test_except_router_uses_set_overwrite(self):
        code, _ = _compile("""
            @flow
            def my_flow(p: dict) -> dict:
                try:
                    p = handler(p)
                except ValueError:
                    p = error_handler(p)
                return p
        """)
        # Except router should use SET (overwrite), not SET[:0] (prepend)
        assert 'yield "SET", ".route.next",' in code

    def test_raise_in_except_terminates_route(self):
        code, _ = _compile("""
            @flow
            def my_flow(p: dict) -> dict:
                try:
                    p = handler(p)
                except ValueError:
                    p = log_error(p)
                    raise
                return p
        """)
        # raise maps to Return, so except router should route to [log_error] only
        # (no continuation after raise)
        assert "log_error" in code

    def test_try_except_with_continuation(self):
        code, _ = _compile("""
            @flow
            def my_flow(p: dict) -> dict:
                try:
                    p = step_a(p)
                except ValueError:
                    p = handle_error(p)
                p = final_step(p)
                return p
        """)
        assert "step_a" in code
        assert "handle_error" in code
        assert "final_step" in code
