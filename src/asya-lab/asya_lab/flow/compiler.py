"""Flow compiler public API.

Pipeline: Parse -> CodeGen -> Manifest -> Analyze -> GraphGen
"""

from __future__ import annotations

import ast
import contextlib
import os
from pathlib import Path
from typing import TYPE_CHECKING

from asya_lab.flow.analyzer import GraphData, analyze
from asya_lab.flow.codegen import ROUTER_PREFIXES, CodeGenerator, CodegenMeta
from asya_lab.flow.graphgen import to_dot, to_json, to_json_string, to_mermaid
from asya_lab.flow.parser import FlowParser, ParseResult
from asya_lab.flow.result_types import ActorInfo, FlowInfo


if TYPE_CHECKING:
    from asya_lab.compiler.rules import RuleEngine
    from asya_lab.config.project import AsyaProject


def _calculate_module_path(filename: str) -> str:
    """Calculate Python module path from filename.

    Converts /path/to/my_project/handlers/processor.py to my_project.handlers.processor
    Uses PYTHONPATH or current working directory as the base.
    """
    filepath = Path(filename).resolve()

    python_paths = [Path(p).resolve() for p in os.environ.get("PYTHONPATH", "").split(":") if p]

    for python_path in python_paths:
        try:
            rel_path = filepath.relative_to(python_path)
            parts = [*list(rel_path.parts[:-1]), rel_path.stem]
            return ".".join(parts)
        except ValueError:
            continue

    return filepath.stem


class FlowCompiler:
    def __init__(
        self,
        verbose: bool = False,
        max_iterations: int = 100,
        rule_engine: RuleEngine | None = None,
        project: AsyaProject | None = None,
    ):
        self.verbose = verbose
        self.max_iterations = max_iterations
        self._rule_engine: RuleEngine | None = rule_engine
        self._project = project
        self.warnings: list[str] = []
        self.flow_name: str | None = None
        self.class_methods: set[str] = set()
        self.is_async: bool = False
        self.import_map: dict[str, str] = {}
        self.handler_source_files: dict[str, Path] = {}  # actor_name -> source file
        self.module_constants: list[str] = []
        self._parse_result: ParseResult | None = None
        self._generated_code: str | None = None
        self._graph_data: GraphData | None = None
        self._codegen_meta: CodegenMeta | None = None

    def compile_file(
        self,
        source_file: str,
        output_dir: str,
        overwrite: bool = False,
        flow_name: str | None = None,
        *,
        routers_dir: str | None = None,
        artifacts_dir: str | None = None,
    ) -> FlowInfo:
        source_path = Path(source_file)
        if not source_path.exists():
            raise FileNotFoundError(f"Source file not found: {source_file}")

        # Resolve output directories — all default to output_dir if not specified
        routers_path = Path(routers_dir) if routers_dir else Path(output_dir)
        artifacts_path = Path(artifacts_dir) if artifacts_dir else Path(output_dir)

        for d in (routers_path, artifacts_path):
            if d.exists() and not d.is_dir():
                raise ValueError(f"Output path exists and is not a directory: {d}")
            d.mkdir(parents=True, exist_ok=True)

        source_code = source_path.read_text()
        compiled_file = routers_path / "routers.py"
        compiled_code = self.compile(source_code, str(source_path), str(compiled_file))
        compiled_file.write_text(compiled_code)

        # Resolve handler FQNs and source files by importing the flow module
        self._resolve_handler_sources(source_path)

        manifests_dir = self._stamp_manifests(routers_path)
        dot, mermaid_content, json_content = self._generate_outputs(artifacts_path)

        if flow_name is None:
            flow_function = self.flow_name or source_path.stem
            flow_name = flow_function.replace("_", "-")
        flow_function = flow_name.replace("-", "_")
        actors = self._build_actor_infos()

        from asya_lab.flow.parser import ActorCall, Mutation

        ops = self._parse_result.operations if self._parse_result else []
        num_actor_calls = sum(1 for op in ops if isinstance(op, ActorCall))
        num_inline_mutations = sum(1 for op in ops if isinstance(op, Mutation))

        return FlowInfo(
            flow_name=flow_name,
            flow_function=flow_function,
            routers_path=compiled_file,
            artifacts_dir=artifacts_path,
            manifests_dir=manifests_dir or routers_path,
            graph=to_json(self._graph_data, flow_function) if self._graph_data else {},
            dot=dot,
            mermaid=mermaid_content,
            actors=actors,
            warnings=list(self.warnings),
            num_actor_calls=num_actor_calls,
            num_inline_mutations=num_inline_mutations,
        )

    def compile(self, source_code: str, filename: str, output_file: str | None = None) -> str:
        # Step 1: Parse
        result = self._parse(source_code, filename)
        self._parse_result = result
        self.warnings.extend(result.warnings)

        # Step 2: CodeGen
        codegen = CodeGenerator(result, filename, output_file)
        code = codegen.generate()
        self._generated_code = code
        self._codegen_meta = codegen.get_meta()

        # Step 3: Analyze (graph extraction from generated code)
        handler_sources = self._extract_handler_sources(source_code, result.actors)
        self._graph_data = analyze(code, handler_sources, self._codegen_meta.actor_retry_rules)
        # Pass through flow composition groups from parser
        if result.groups:
            self._graph_data.groups = result.groups
        self.warnings.extend(self._graph_data.warnings)

        self.flow_name = result.flow_name

        return code

    def validate(self, source_code: str, filename: str) -> None:
        self._parse(source_code, filename)

    def generate_plot(
        self,
        output_dir: str,
        plot_format: str = "png",
    ) -> tuple[str, str | None]:
        if not self.flow_name or self._graph_data is None:
            raise RuntimeError("Must compile flow before generating plot")

        dot_content = to_dot(self._graph_data, self.flow_name)
        mmd_content = to_mermaid(self._graph_data, self.flow_name)
        json_content = to_json_string(self._graph_data, self.flow_name)

        output_path = Path(output_dir)
        dot_file = output_path / "flow.dot"
        dot_file.write_text(dot_content)

        mmd_file = output_path / "flow.mmd"
        mmd_file.write_text(mmd_content)

        json_file = output_path / "graph.json"
        json_file.write_text(json_content)

        output_path_str = None
        try:
            import subprocess  # nosec B404

            subprocess.run(["dot", "-V"], capture_output=True, check=True)  # nosec B603, B607

            output_file = output_path / f"flow.{plot_format}"

            subprocess.run(  # nosec B603, B607
                ["dot", f"-T{plot_format}", str(dot_file), "-o", str(output_file)],
                capture_output=True,
                text=True,
                check=True,
            )
            output_path_str = str(output_file)

        except FileNotFoundError as e:
            raise ImportError(
                "graphviz 'dot' command not found. Install graphviz to generate plots. "
                "On Ubuntu/Debian: apt-get install graphviz"
            ) from e
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"graphviz dot failed: {e.stderr}") from e

        return str(dot_file), output_path_str

    @property
    def single_actor_name(self) -> str | None:
        """Returns the actor name if this is a single-actor flow, else None."""
        if self._parse_result is None:
            return None
        from asya_lab.flow.parser import ActorCall, Return

        ops = self._parse_result.operations
        actor_calls = [op for op in ops if isinstance(op, ActorCall)]
        non_actor = [op for op in ops if not isinstance(op, ActorCall | Return)]
        if len(actor_calls) == 1 and len(non_actor) == 0:
            return actor_calls[0].name
        return None

    def get_warnings(self) -> list[str]:
        return self.warnings

    def _generate_outputs(self, output_path: Path) -> tuple[str, str, str]:
        if not self.flow_name or self._graph_data is None:
            return "", "", ""

        dot_content = to_dot(self._graph_data, self.flow_name)
        mmd_content = to_mermaid(self._graph_data, self.flow_name)
        json_content = to_json_string(self._graph_data, self.flow_name)

        (output_path / "flow.dot").write_text(dot_content)
        (output_path / "flow.mmd").write_text(mmd_content)
        (output_path / "graph.json").write_text(json_content)

        self._try_render_plot(output_path)
        return dot_content, mmd_content, json_content

    def _try_render_plot(self, output_path: Path) -> None:
        dot_file = output_path / "flow.dot"
        png_file = output_path / "flow.png"
        try:
            import subprocess  # nosec B404

            subprocess.run(["dot", "-V"], capture_output=True, check=True)  # nosec B603, B607
            subprocess.run(  # nosec B603, B607
                ["dot", "-Tpng", str(dot_file), "-o", str(png_file)],
                capture_output=True,
                text=True,
                check=True,
            )
        except (FileNotFoundError, subprocess.CalledProcessError):
            pass

    def _stamp_manifests(self, compiled_dir: Path) -> Path | None:
        if self._project is None or self._codegen_meta is None:
            return None
        if self._codegen_meta.single_actor is not None:
            return None

        from asya_lab.compiler.templater import ManifestTemplater

        flow_function = self.flow_name
        if not flow_function:
            return None

        flow_name = flow_function.replace("_", "-")

        try:
            # flow_name already interpolated via ${arg:flow_name} in config
            manifests_dir = self._project.resolve_path("compiler.manifests")
            templates_dir = self._project.resolve_path("compiler.templates")
        except KeyError:
            return None

        router_code = self._generated_code or ""
        actor_template = templates_dir / "actor.yaml"
        if not actor_template.exists():
            return None

        def _opt(name: str) -> Path | None:
            p = templates_dir / name
            return p if p.exists() else None

        templater = ManifestTemplater(
            flow_name=flow_name,
            flow_function=flow_function,
            codegen_meta=self._codegen_meta,
            router_code=router_code,
            project=self._project,
            actor_template_path=actor_template,
            router_template_path=_opt("router.yaml"),
            configmap_routers_template_path=_opt("configmap-routers.yaml"),
            kustomization_template_path=_opt("kustomization.yaml"),
            import_map=self.import_map,
            handler_source_files=self.handler_source_files,
            flow_roles=self._detect_flow_roles(),
        )
        templater.stamp(manifests_dir)
        return manifests_dir

    def _build_actor_infos(self) -> list[ActorInfo]:
        if self._codegen_meta is None:
            return []

        actors = []
        flow_roles = self._detect_flow_roles()

        for router_name in self._codegen_meta.router_names:
            k8s_name = router_name.replace("_", "-")
            actors.append(
                ActorInfo(
                    name=k8s_name,
                    handler=f"routers.{router_name}",
                    image="",
                    role=flow_roles.get(router_name, "router"),
                    generated=True,
                )
            )

        for handler_name in sorted(self._codegen_meta.all_handler_names):
            if any(handler_name.startswith(p) for p in ROUTER_PREFIXES):
                continue
            k8s_name = f"actor-{handler_name.replace('_', '-')}"
            actors.append(
                ActorInfo(
                    name=k8s_name,
                    handler=self.import_map.get(handler_name, handler_name),
                    image="",
                    role=flow_roles.get(handler_name, "actor"),
                )
            )

        return actors

    def _detect_flow_roles(self) -> dict[str, str]:
        if self._graph_data is None:
            return {}
        roles: dict[str, str] = {}
        for node in self._graph_data.nodes:
            node_id = node.get("id", "")
            role = node.get("role", "")
            if role:
                roles[node_id] = role
        return roles

    def _resolve_handler_sources(self, flow_source: Path) -> None:
        """Import the flow module and resolve each handler's FQN and source file.

        Uses the running Python interpreter — the same environment the user
        tested their flow in locally.
        """
        import importlib
        import importlib.util
        import inspect

        if not self._parse_result:
            return

        actor_names = self._parse_result.actors
        if not actor_names:
            return

        # Import the flow file as a proper module
        # Try to find its package by looking for __init__.py
        flow_dir = flow_source.parent
        module_name = flow_source.stem

        # Walk up to find the package root (directory with __init__.py whose parent has none)
        package_parts: list[str] = [module_name]
        current = flow_dir
        while (current / "__init__.py").exists():
            package_parts.insert(0, current.name)
            current = current.parent

        fqn_module = ".".join(package_parts)

        try:
            mod = importlib.import_module(fqn_module)
        except ImportError:
            # Fall back: try importing from the file directly
            try:
                spec = importlib.util.spec_from_file_location(module_name, flow_source)
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                else:
                    return
            except Exception:
                self.warnings.append(
                    f"Could not import flow module '{fqn_module}' — "
                    f"handler source files will not be resolved for skaffold image mapping. "
                    f"Ensure the flow file is importable in the current Python environment."
                )
                return

        for actor_name in actor_names:
            func = getattr(mod, actor_name, None)
            if func is None or not callable(func):
                continue

            handler_fqn = f"{func.__module__}.{func.__qualname__}"
            self.import_map[actor_name] = handler_fqn

            try:
                source_file = Path(inspect.getfile(func)).resolve()
                self.handler_source_files[actor_name] = source_file
                if self.verbose:
                    import click

                    click.echo(f"    [.] {actor_name} -> {handler_fqn} ({source_file})")
            except (TypeError, OSError):
                pass

    @staticmethod
    def _extract_handler_sources(source_code: str, actor_names: list[str]) -> dict[str, str]:
        """Extract source code of handler functions referenced by the flow.

        Enables the analyzer to discover override edges (yield SET routes)
        defined inside actor handlers, not just in generated routers.
        """
        if not actor_names:
            return {}
        try:
            tree = ast.parse(source_code)
        except SyntaxError:
            return {}
        names = set(actor_names)
        result: dict[str, str] = {}
        for node in tree.body:
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name in names:
                result[node.name] = ast.unparse(node)
        return result

    def _parse(self, source_code: str, filename: str) -> ParseResult:
        module_path = _calculate_module_path(filename)
        ctx_rules = None
        if self._project is not None:
            with contextlib.suppress(KeyError, FileNotFoundError):
                ctx_rules = self._project.load_context_manager_rules()
        parser = FlowParser(source_code, filename, module_path, rules=ctx_rules, rule_engine=self._rule_engine)
        result = parser.parse()
        self.class_methods = result.class_methods
        self.is_async = result.is_async
        self.import_map = result.import_map
        self.module_constants = result.constants
        return result
