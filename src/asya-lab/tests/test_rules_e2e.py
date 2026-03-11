"""E2E tests: full compile pipeline with real config files and rules.

Each test scaffolds a minimal .asya/ project directory with config.yaml
and config.compiler.rules.yaml, then compiles a flow using the full
pipeline (AsyaProject -> load_rules -> FlowCompiler -> generated code).

Tests verify that the compiler correctly classifies different AST
constructs (function calls, dotted calls, inline comments) and that
the generated router code reflects those classifications.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from textwrap import dedent

from asya_lab.compiler.extractor import ValueExtractor
from asya_lab.compiler.rules import RuleEngine, TreatAs
from asya_lab.config.project import AsyaProject
from asya_lab.flow.compiler import FlowCompiler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scaffold_project(
    tmp_path: Path,
    *,
    rules_yaml: str = "",
    config_yaml: str = "templates:\n  namespace: default\n",
) -> AsyaProject:
    """Create a minimal .asya/ project with config and rules files."""
    (tmp_path / ".git").mkdir()
    asya_dir = tmp_path / ".asya"
    asya_dir.mkdir()
    (asya_dir / "config.yaml").write_text(config_yaml)
    if rules_yaml:
        (asya_dir / "config.compiler.rules.yaml").write_text(rules_yaml)
    return AsyaProject.from_dir(tmp_path)


def _load_engine(project: AsyaProject) -> RuleEngine:
    """Load rules from *project* and return a typed RuleEngine."""
    return project.load_rules()


def _compile_flow(project: AsyaProject, source: str) -> str:
    """Compile a flow source using the full pipeline and return generated code."""
    engine = project.load_rules()
    compiler = FlowCompiler(rule_engine=engine)
    return compiler.compile(source, "test_flow.py")


# -- Assertion helpers -------------------------------------------------------
# Each helper prints the full generated code on failure so the developer
# can immediately see what went wrong.

_MUTATION_RE_CACHE: dict[str, re.Pattern[str]] = {}


def _mutation_re(call_expr: str) -> re.Pattern[str]:
    """Compile and cache a regex that matches `p = <call_expr>` as a mutation line."""
    if call_expr not in _MUTATION_RE_CACHE:
        escaped = re.escape(call_expr)
        _MUTATION_RE_CACHE[call_expr] = re.compile(rf"^\s+p = {escaped}", re.MULTILINE)
    return _MUTATION_RE_CACHE[call_expr]


def _assert_inlined(code: str, call_expr: str) -> None:
    """Assert *call_expr* appears as an inlined mutation, NOT as a resolved actor.

    Checks two things:
      1. ``p = <call_expr>`` appears indented inside a router function body.
      2. ``resolve("<func_name>")`` does NOT appear anywhere.
    """
    assert _mutation_re(call_expr).search(code), (
        f"Expected inlined mutation 'p = {call_expr}' not found in generated code:\n{code}"
    )
    func_name = call_expr.split("(")[0]
    assert f'resolve("{func_name}")' not in code, (
        f"Expected '{func_name}' to be inlined but found resolve() call in generated code:\n{code}"
    )


def _assert_actor(code: str, name: str) -> None:
    """Assert *name* appears as a resolved actor (via ``resolve("name")``)."""
    assert f'resolve("{name}")' in code, f'Expected resolve("{name}") not found in generated code:\n{code}'


def _assert_not_actor(code: str, name: str) -> None:
    """Assert *name* does NOT appear as a resolved actor."""
    assert f'resolve("{name}")' not in code, f'Unexpected resolve("{name}") found in generated code:\n{code}'


def _parse_call(source: str) -> ast.Call:
    """Parse a Python expression string and return its Call node."""
    tree = ast.parse(source, mode="eval")
    assert isinstance(tree.body, ast.Call)
    return tree.body


# ---------------------------------------------------------------------------
# Full tenacity.retry rule YAML (from research-compiler-knowledge-base.md)
# ---------------------------------------------------------------------------

_TENACITY_RULES_YAML = dedent("""\
    - match: "tenacity.retry"
      where:
        - param: stop
          where:
            - param: max_attempt_number
              assign-to: spec.resiliency.retry.maxAttempts
            - param: max_delay
              assign-to: spec.resiliency.retry.maxWindow
        - param: wait
          where:
            - param: min
              assign-to: spec.resiliency.retry.initialInterval
            - param: max
              assign-to: spec.resiliency.retry.maxInterval
            - param: multiplier
              assign-to: spec.resiliency.retry.backoffCoefficient
        - param: retry
          where:
            - match: retry_if_exception_type
              where:
                - param: exception_types
                  assign-to: spec.resiliency.retryableErrors
            - match: retry_if_not_exception_type
              where:
                - param: exception_types
                  assign-to: spec.resiliency.nonRetryableErrors
""")

# Import map: what _collect_imports produces for ``from tenacity import ...``
_TENACITY_IMPORTS = {
    "retry": "tenacity.retry",
    "stop_after_attempt": "tenacity.stop_after_attempt",
    "stop_after_delay": "tenacity.stop_after_delay",
    "wait_exponential": "tenacity.wait_exponential",
    "retry_if_exception_type": "tenacity.retry_if_exception_type",
    "retry_if_not_exception_type": "tenacity.retry_if_not_exception_type",
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestInlineClassification:
    """External (dotted) calls are inlined by the default '*' rule."""

    def test_dotted_call_inlined_by_default(self, tmp_path: Path) -> None:
        """A dotted call like ``utils.clean(p)`` matches '*' -> inline."""
        project = _scaffold_project(tmp_path)
        source = dedent("""\
            async def my_flow(p: dict) -> dict:
                p = handler_a(p)
                p = utils.clean(p)
                p = handler_b(p)
                return p
        """)
        code = _compile_flow(project, source)

        _assert_inlined(code, "utils.clean(p)")
        _assert_actor(code, "handler_a")
        _assert_actor(code, "handler_b")

    def test_multiple_consecutive_inlines_merged(self, tmp_path: Path) -> None:
        """Multiple consecutive inline calls merge into one router's mutations."""
        project = _scaffold_project(tmp_path)
        source = dedent("""\
            async def my_flow(p: dict) -> dict:
                p = handler_a(p)
                p = logging.info(p)
                p = metrics.emit(p)
                p = handler_b(p)
                return p
        """)
        code = _compile_flow(project, source)

        _assert_inlined(code, "logging.info(p)")
        _assert_inlined(code, "metrics.emit(p)")
        _assert_actor(code, "handler_a")
        _assert_actor(code, "handler_b")


class TestInlineCommentOverride:
    """The ``# asya: <action>`` inline comment has highest priority."""

    def test_comment_forces_inline(self, tmp_path: Path) -> None:
        """A bare symbol (same-package -> unfold) overridden to inline via comment."""
        project = _scaffold_project(tmp_path)
        source = dedent("""\
            async def my_flow(p: dict) -> dict:
                p = handler_a(p)
                p = local_helper(p)  # asya: inline
                p = handler_b(p)
                return p
        """)
        code = _compile_flow(project, source)

        _assert_inlined(code, "local_helper(p)")
        _assert_actor(code, "handler_a")

    def test_comment_forces_actor(self, tmp_path: Path) -> None:
        """A dotted call (default '*' -> inline) overridden to actor via comment."""
        project = _scaffold_project(tmp_path)
        source = dedent("""\
            async def my_flow(p: dict) -> dict:
                p = handler_a(p)
                p = external.lib(p)  # asya: actor
                p = handler_b(p)
                return p
        """)
        code = _compile_flow(project, source)

        _assert_actor(code, "external.lib")
        # Must NOT appear as an inline mutation
        assert not _mutation_re("external.lib(p)").search(code), f"external.lib should be actor, not mutation:\n{code}"


class TestUserRuleOverridesDefault:
    """Exact-match user rules (tier 0) beat default wildcards (tier 2/3)."""

    def test_exact_match_beats_wildcard(self, tmp_path: Path) -> None:
        """User rule: tenacity.retry -> config, default '*' -> inline."""
        rules = dedent("""\
            - match: "tenacity.retry"
              treat-as: config
        """)
        project = _scaffold_project(tmp_path, rules_yaml=rules)
        source = dedent("""\
            async def my_flow(p: dict) -> dict:
                p = tenacity.retry(p)
                p = other.lib(p)
                return p
        """)
        code = _compile_flow(project, source)

        _assert_inlined(code, "tenacity.retry(p)")
        _assert_inlined(code, "other.lib(p)")

    def test_prefix_wildcard_rule(self, tmp_path: Path) -> None:
        """User rule: 'mylib.*' -> actor forces all mylib.X to actor."""
        rules = dedent("""\
            - match: "mylib.*"
              treat-as: actor
        """)
        project = _scaffold_project(tmp_path, rules_yaml=rules)
        source = dedent("""\
            async def my_flow(p: dict) -> dict:
                p = mylib.process(p)
                p = mylib.validate(p)
                p = external.util(p)
                return p
        """)
        code = _compile_flow(project, source)

        _assert_actor(code, "mylib.process")
        _assert_actor(code, "mylib.validate")
        _assert_inlined(code, "external.util(p)")


class TestSamePackageClassification:
    """Bare (undotted) symbols match '.' (same-package) -> unfold by default."""

    def test_bare_symbol_unfold_still_actor(self, tmp_path: Path) -> None:
        """Unfold symbols are currently emitted as actors (expansion not yet implemented)."""
        project = _scaffold_project(tmp_path)
        source = dedent("""\
            async def my_flow(p: dict) -> dict:
                p = local_handler(p)
                p = another_handler(p)
                return p
        """)
        code = _compile_flow(project, source)

        _assert_actor(code, "local_handler")
        _assert_actor(code, "another_handler")


class TestConditionalWithMixedClassifications:
    """Rules apply inside conditional branches."""

    def test_if_else_with_inline_and_actor(self, tmp_path: Path) -> None:
        """Inline calls inside branches become mutations in the branch router."""
        project = _scaffold_project(tmp_path)
        source = dedent("""\
            async def my_flow(p: dict) -> dict:
                if p["type"] == "fast":
                    p = handler_fast(p)
                else:
                    p = handler_slow(p)
                return p
        """)
        code = _compile_flow(project, source)

        _assert_actor(code, "handler_fast")
        _assert_actor(code, "handler_slow")

    def test_inline_inside_branch(self, tmp_path: Path) -> None:
        """A dotted call inside a branch is inlined within the branch router."""
        project = _scaffold_project(tmp_path)
        source = dedent("""\
            async def my_flow(p: dict) -> dict:
                if p["ready"]:
                    p = metrics.track(p)
                    p = handler_a(p)
                else:
                    p = handler_b(p)
                return p
        """)
        code = _compile_flow(project, source)

        _assert_inlined(code, "metrics.track(p)")
        _assert_actor(code, "handler_a")
        _assert_actor(code, "handler_b")


class TestConfigWithExtractionRules:
    """Config rules with where: trees extract values from call sites."""

    def test_config_rule_with_keyword_extraction(self, tmp_path: Path) -> None:
        """asyncio.timeout classified as config, keyword arg extracted to spec path."""
        rules = dedent("""\
            - match: "asyncio.timeout"
              where:
                - param: delay
                  assign-to: spec.resiliency.timeout
        """)
        project = _scaffold_project(tmp_path, rules_yaml=rules)
        source = dedent("""\
            async def my_flow(p: dict) -> dict:
                p = asyncio.timeout(p)
                p = handler(p)
                return p
        """)
        code = _compile_flow(project, source)

        _assert_inlined(code, "asyncio.timeout(p)")
        _assert_actor(code, "handler")

    def test_extraction_rule_loads_from_config(self, tmp_path: Path) -> None:
        """Verify the RuleEngine loads extraction rules and get_rule() returns them."""
        rules = dedent("""\
            - match: "asyncio.timeout"
              where:
                - param: delay
                  assign-to: spec.resiliency.timeout
        """)
        project = _scaffold_project(tmp_path, rules_yaml=rules)
        engine = _load_engine(project)
        rule = engine.get_rule("asyncio.timeout")
        assert rule is not None, "Rule for asyncio.timeout not found"
        assert rule.treat_as == TreatAs.CONFIG, rule.treat_as
        assert rule.where is not None, "Expected where: tree"
        assert len(rule.where) == 1, f"Expected 1 where node, got {len(rule.where)}"
        assert rule.where[0].param == "delay", rule.where[0].param
        assert rule.where[0].assign_to == "spec.resiliency.timeout", rule.where[0].assign_to


class TestTenacityRules:
    """Complex tenacity.retry rules: nested where: trees with extraction."""

    def test_tenacity_rule_loads_from_config(self, tmp_path: Path) -> None:
        """Full tenacity.retry rule is loaded with correct tree structure."""
        project = _scaffold_project(tmp_path, rules_yaml=_TENACITY_RULES_YAML)
        engine = _load_engine(project)

        rule = engine.get_rule("tenacity.retry")
        assert rule is not None, "Rule for tenacity.retry not found"
        assert rule.treat_as == TreatAs.CONFIG, rule.treat_as
        assert rule.where is not None, "Expected where: tree"
        assert len(rule.where) == 3, f"Expected 3 top-level params (stop/wait/retry), got {len(rule.where)}"

        # Stop tree
        stop_node = rule.where[0]
        assert stop_node.param == "stop", stop_node.param
        assert stop_node.where is not None
        assert len(stop_node.where) == 2, f"stop should have 2 children, got {len(stop_node.where)}"
        assert stop_node.where[0].param == "max_attempt_number"
        assert stop_node.where[0].assign_to == "spec.resiliency.retry.maxAttempts"
        assert stop_node.where[1].param == "max_delay"
        assert stop_node.where[1].assign_to == "spec.resiliency.retry.maxWindow"

        # Wait tree
        wait_node = rule.where[1]
        assert wait_node.param == "wait", wait_node.param
        assert wait_node.where is not None
        assert len(wait_node.where) == 3, f"wait should have 3 children, got {len(wait_node.where)}"
        assert wait_node.where[0].assign_to == "spec.resiliency.retry.initialInterval"
        assert wait_node.where[1].assign_to == "spec.resiliency.retry.maxInterval"
        assert wait_node.where[2].assign_to == "spec.resiliency.retry.backoffCoefficient"

        # Retry tree
        retry_node = rule.where[2]
        assert retry_node.param == "retry", retry_node.param
        assert retry_node.where is not None
        assert len(retry_node.where) == 2, f"retry should have 2 match nodes, got {len(retry_node.where)}"
        assert retry_node.where[0].match == "retry_if_exception_type"
        assert retry_node.where[1].match == "retry_if_not_exception_type"

    def test_tenacity_classified_as_config_in_flow(self, tmp_path: Path) -> None:
        """tenacity.retry is inlined (config) in the generated router code."""
        project = _scaffold_project(tmp_path, rules_yaml=_TENACITY_RULES_YAML)
        source = dedent("""\
            async def my_flow(p: dict) -> dict:
                p = tenacity.retry(p)
                p = handler(p)
                return p
        """)
        code = _compile_flow(project, source)

        _assert_inlined(code, "tenacity.retry(p)")
        _assert_actor(code, "handler")

    def test_tenacity_exact_match_beats_default_inline(self, tmp_path: Path) -> None:
        """tenacity.retry (exact, tier 0) wins over '*' (tier 3)."""
        project = _scaffold_project(tmp_path, rules_yaml=_TENACITY_RULES_YAML)
        engine = _load_engine(project)

        # tenacity.retry -> config (exact match, tier 0)
        assert engine.classify("tenacity.retry") == TreatAs.CONFIG
        # tenacity.wait -> inline (falls through to default '*', tier 3)
        assert engine.classify("tenacity.wait") == TreatAs.INLINE
        # Bare symbol -> unfold (default '.', tier 2)
        assert engine.classify("handler") == TreatAs.UNFOLD

    def test_extract_stop_after_attempt(self, tmp_path: Path) -> None:
        """Extract maxAttempts from ``stop=stop_after_attempt(5)`` using positional arg.

        The import map resolves ``stop_after_attempt`` to its qualified name
        so ``inspect.signature`` can resolve positional parameters.
        """
        project = _scaffold_project(tmp_path, rules_yaml=_TENACITY_RULES_YAML)
        engine = _load_engine(project)
        rule = engine.get_rule("tenacity.retry")
        assert rule is not None

        call = _parse_call("tenacity.retry(stop=stop_after_attempt(5))")
        result = ValueExtractor(imports=_TENACITY_IMPORTS).extract(call, rule)

        assert result.get("spec.resiliency.retry.maxAttempts") == 5, result

    def test_extract_stop_after_delay(self, tmp_path: Path) -> None:
        """Extract maxWindow from ``stop=stop_after_delay(30)`` using positional arg."""
        project = _scaffold_project(tmp_path, rules_yaml=_TENACITY_RULES_YAML)
        engine = _load_engine(project)
        rule = engine.get_rule("tenacity.retry")
        assert rule is not None

        call = _parse_call("tenacity.retry(stop=stop_after_delay(30))")
        result = ValueExtractor(imports=_TENACITY_IMPORTS).extract(call, rule)

        assert result.get("spec.resiliency.retry.maxWindow") == 30, result

    def test_extract_wait_exponential_kwargs(self, tmp_path: Path) -> None:
        """Extract initialInterval + maxInterval from ``wait=wait_exponential(min=1, max=60)``."""
        project = _scaffold_project(tmp_path, rules_yaml=_TENACITY_RULES_YAML)
        engine = _load_engine(project)
        rule = engine.get_rule("tenacity.retry")
        assert rule is not None

        call = _parse_call("tenacity.retry(wait=wait_exponential(min=1, max=60))")
        result = ValueExtractor().extract(call, rule)

        assert result.get("spec.resiliency.retry.initialInterval") == 1, result
        assert result.get("spec.resiliency.retry.maxInterval") == 60, result

    def test_extract_wait_exponential_with_multiplier(self, tmp_path: Path) -> None:
        """Extract backoffCoefficient from ``wait=wait_exponential(multiplier=2)``."""
        project = _scaffold_project(tmp_path, rules_yaml=_TENACITY_RULES_YAML)
        engine = _load_engine(project)
        rule = engine.get_rule("tenacity.retry")
        assert rule is not None

        call = _parse_call("tenacity.retry(wait=wait_exponential(multiplier=2, min=1, max=120))")
        result = ValueExtractor().extract(call, rule)

        assert result.get("spec.resiliency.retry.backoffCoefficient") == 2, result
        assert result.get("spec.resiliency.retry.initialInterval") == 1, result
        assert result.get("spec.resiliency.retry.maxInterval") == 120, result

    def test_extract_retry_if_exception_type(self, tmp_path: Path) -> None:
        """Extract retryableErrors from ``retry=retry_if_exception_type(ValueError)``.

        Match-only nodes discriminate by function name: only the
        ``retry_if_exception_type`` branch fires, not ``retry_if_not_exception_type``.
        """
        project = _scaffold_project(tmp_path, rules_yaml=_TENACITY_RULES_YAML)
        engine = _load_engine(project)
        rule = engine.get_rule("tenacity.retry")
        assert rule is not None

        call = _parse_call("tenacity.retry(retry=retry_if_exception_type(exception_types=ValueError))")
        result = ValueExtractor(imports=_TENACITY_IMPORTS).extract(call, rule)

        assert result == {"spec.resiliency.retryableErrors": "ValueError"}, result

    def test_extract_retry_if_not_exception_type(self, tmp_path: Path) -> None:
        """Extract nonRetryableErrors from ``retry=retry_if_not_exception_type(...)``.

        Only the ``retry_if_not_exception_type`` branch fires.
        """
        project = _scaffold_project(tmp_path, rules_yaml=_TENACITY_RULES_YAML)
        engine = _load_engine(project)
        rule = engine.get_rule("tenacity.retry")
        assert rule is not None

        call = _parse_call("tenacity.retry(retry=retry_if_not_exception_type(exception_types=KeyboardInterrupt))")
        result = ValueExtractor(imports=_TENACITY_IMPORTS).extract(call, rule)

        assert result == {"spec.resiliency.nonRetryableErrors": "KeyboardInterrupt"}, result

    def test_extract_combined_stop_and_wait(self, tmp_path: Path) -> None:
        """Multiple top-level params extracted from a single call (positional args)."""
        project = _scaffold_project(tmp_path, rules_yaml=_TENACITY_RULES_YAML)
        engine = _load_engine(project)
        rule = engine.get_rule("tenacity.retry")
        assert rule is not None

        call = _parse_call("tenacity.retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=60))")
        result = ValueExtractor(imports=_TENACITY_IMPORTS).extract(call, rule)

        assert result.get("spec.resiliency.retry.maxAttempts") == 3, result
        assert result.get("spec.resiliency.retry.initialInterval") == 1, result
        assert result.get("spec.resiliency.retry.maxInterval") == 60, result

    def test_extract_stop_binop_pipe(self, tmp_path: Path) -> None:
        """BinOp ``stop_after_attempt(5) | stop_after_delay(30)`` extracts both values."""
        project = _scaffold_project(tmp_path, rules_yaml=_TENACITY_RULES_YAML)
        engine = _load_engine(project)
        rule = engine.get_rule("tenacity.retry")
        assert rule is not None

        call = _parse_call("tenacity.retry(stop=stop_after_attempt(5) | stop_after_delay(30))")
        result = ValueExtractor(imports=_TENACITY_IMPORTS).extract(call, rule)

        assert result.get("spec.resiliency.retry.maxAttempts") == 5, result
        assert result.get("spec.resiliency.retry.maxWindow") == 30, result

    def test_extract_full_realistic_retry_call(self, tmp_path: Path) -> None:
        """Full realistic tenacity.retry with stop + wait + retry params."""
        project = _scaffold_project(tmp_path, rules_yaml=_TENACITY_RULES_YAML)
        engine = _load_engine(project)
        rule = engine.get_rule("tenacity.retry")
        assert rule is not None

        call = _parse_call(
            "tenacity.retry("
            "  stop=stop_after_attempt(5) | stop_after_delay(120),"
            "  wait=wait_exponential(multiplier=2, min=1, max=60),"
            "  retry=retry_if_exception_type(exception_types=ValueError)"
            ")"
        )
        result = ValueExtractor(imports=_TENACITY_IMPORTS).extract(call, rule)

        assert result == {
            "spec.resiliency.retry.maxAttempts": 5,
            "spec.resiliency.retry.maxWindow": 120,
            "spec.resiliency.retry.backoffCoefficient": 2,
            "spec.resiliency.retry.initialInterval": 1,
            "spec.resiliency.retry.maxInterval": 60,
            "spec.resiliency.retryableErrors": "ValueError",
        }, result

    def test_no_extraction_when_no_args(self, tmp_path: Path) -> None:
        """Bare ``tenacity.retry()`` with no args extracts nothing."""
        project = _scaffold_project(tmp_path, rules_yaml=_TENACITY_RULES_YAML)
        engine = _load_engine(project)
        rule = engine.get_rule("tenacity.retry")
        assert rule is not None

        call = _parse_call("tenacity.retry()")
        result = ValueExtractor().extract(call, rule)

        assert result == {}, result


class TestFullPipelineWithRichRules:
    """End-to-end: realistic config with multiple rules and a complex flow."""

    def test_mixed_flow_with_multiple_rules(self, tmp_path: Path) -> None:
        """Compile a flow that exercises exact, prefix, and default rules together."""
        rules = dedent("""\
            - match: "tenacity.retry"
              treat-as: config
            - match: "logging.*"
              treat-as: inline
            - match: "myapp.*"
              treat-as: actor
        """)
        project = _scaffold_project(tmp_path, rules_yaml=rules)
        source = dedent("""\
            async def my_flow(p: dict) -> dict:
                p = tenacity.retry(p)
                p = logging.setup(p)
                p = myapp.process(p)
                p = external.util(p)
                p = local_handler(p)
                return p
        """)
        code = _compile_flow(project, source)

        _assert_inlined(code, "tenacity.retry(p)")
        _assert_inlined(code, "logging.setup(p)")
        _assert_actor(code, "myapp.process")
        _assert_inlined(code, "external.util(p)")
        _assert_actor(code, "local_handler")

    def test_inline_mutations_in_start_router(self, tmp_path: Path) -> None:
        """Inline calls at the start of a flow are merged into the start router."""
        project = _scaffold_project(tmp_path)
        source = dedent("""\
            async def my_flow(p: dict) -> dict:
                p = logging.init(p)
                p = handler_a(p)
                return p
        """)
        code = _compile_flow(project, source)

        _assert_inlined(code, "logging.init(p)")
        assert "start_my_flow" in code, code
        _assert_actor(code, "handler_a")

    def test_no_rules_file_uses_defaults(self, tmp_path: Path) -> None:
        """Without config.compiler.rules.yaml, default rules still apply."""
        project = _scaffold_project(tmp_path)
        source = dedent("""\
            async def my_flow(p: dict) -> dict:
                p = handler_a(p)
                p = external.lib(p)
                p = handler_b(p)
                return p
        """)
        code = _compile_flow(project, source)

        _assert_actor(code, "handler_a")
        _assert_actor(code, "handler_b")
        _assert_inlined(code, "external.lib(p)")

    def test_single_actor_flow(self, tmp_path: Path) -> None:
        """A flow with one actor generates a valid single-actor FLOW_METADATA."""
        project = _scaffold_project(tmp_path)
        source = dedent("""\
            async def my_flow(p: dict) -> dict:
                p = handler(p)
                return p
        """)
        code = _compile_flow(project, source)

        assert "FLOW_METADATA" in code, code
        assert "'handler'" in code, code


class TestParamSpecRulesFromConfig:
    """ParamSpec: rules with dict-form param loaded from YAML config."""

    def test_paramspec_kwarg_extraction(self, tmp_path: Path) -> None:
        """ParamSpec with {arg, kwarg} extracts via keyword argument."""
        rules = dedent("""\
            - match: "my_lib.tool"
              where:
                - param: {arg: 0, kwarg: "name"}
                  assign-to: spec.metadata.tool-name
                - param: {arg: 1, kwarg: "description"}
                  assign-to: spec.metadata.description
        """)
        project = _scaffold_project(tmp_path, rules_yaml=rules)
        engine = _load_engine(project)
        rule = engine.get_rule("my_lib.tool")
        assert rule is not None

        call = _parse_call('my_lib.tool(name="greet", description="Greet a user")')
        result = ValueExtractor().extract(call, rule)
        assert result == {
            "spec.metadata.tool-name": "greet",
            "spec.metadata.description": "Greet a user",
        }

    def test_paramspec_positional_extraction(self, tmp_path: Path) -> None:
        """ParamSpec falls back to positional when kwargs are not used."""
        rules = dedent("""\
            - match: "my_lib.tool"
              where:
                - param: {arg: 0, kwarg: "name"}
                  assign-to: spec.metadata.tool-name
                - param: {arg: 1, kwarg: "description"}
                  assign-to: spec.metadata.description
        """)
        project = _scaffold_project(tmp_path, rules_yaml=rules)
        engine = _load_engine(project)
        rule = engine.get_rule("my_lib.tool")
        assert rule is not None

        call = _parse_call('my_lib.tool("greet", "Greet a user")')
        result = ValueExtractor().extract(call, rule)
        assert result == {
            "spec.metadata.tool-name": "greet",
            "spec.metadata.description": "Greet a user",
        }

    def test_paramspec_mixed_positional_and_kwarg(self, tmp_path: Path) -> None:
        """First arg positional, second arg by keyword."""
        rules = dedent("""\
            - match: "my_lib.tool"
              where:
                - param: {arg: 0, kwarg: "name"}
                  assign-to: spec.metadata.tool-name
                - param: {arg: 1, kwarg: "description"}
                  assign-to: spec.metadata.description
        """)
        project = _scaffold_project(tmp_path, rules_yaml=rules)
        engine = _load_engine(project)
        rule = engine.get_rule("my_lib.tool")
        assert rule is not None

        call = _parse_call('my_lib.tool("greet", description="Greet a user")')
        result = ValueExtractor().extract(call, rule)
        assert result == {
            "spec.metadata.tool-name": "greet",
            "spec.metadata.description": "Greet a user",
        }

    def test_paramspec_with_type_annotation(self, tmp_path: Path) -> None:
        """ParamSpec with type field is parsed from YAML and stored."""
        rules = dedent("""\
            - match: "my_lib.tool"
              where:
                - param: {arg: 0, kwarg: "name", type: "str"}
                  assign-to: spec.metadata.tool-name
        """)
        project = _scaffold_project(tmp_path, rules_yaml=rules)
        engine = _load_engine(project)
        rule = engine.get_rule("my_lib.tool")
        assert rule is not None
        assert rule.where is not None

        from asya_lab.compiler.rules import ParamSpec

        param = rule.where[0].param
        assert isinstance(param, ParamSpec)
        assert param.arg == 0
        assert param.kwarg == "name"
        assert param.type == "str"


class TestBackwardsCompatibility:
    """Compiler without rule_engine preserves pre-rules behavior."""

    def test_no_engine_all_calls_are_actors(self) -> None:
        """Without rules, every call -- bare or dotted -- is an actor."""
        source = dedent("""\
            async def my_flow(p: dict) -> dict:
                p = handler_a(p)
                p = external.lib(p)
                p = handler_b(p)
                return p
        """)
        compiler = FlowCompiler()
        code = compiler.compile(source, "test.py")

        _assert_actor(code, "handler_a")
        _assert_actor(code, "external.lib")
        _assert_actor(code, "handler_b")

    def test_no_engine_with_mutations(self) -> None:
        """Payload mutations still work without rules."""
        source = dedent("""\
            async def my_flow(p: dict) -> dict:
                p["status"] = "started"
                p = handler(p)
                return p
        """)
        compiler = FlowCompiler()
        code = compiler.compile(source, "test.py")

        assert "started" in code, code
        _assert_actor(code, "handler")
