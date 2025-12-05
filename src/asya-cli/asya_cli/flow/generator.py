"""
Router code generator for Flow DSL.

Generates router functions from Flow IR.
"""

from asya_cli.flow.ir import (
    Break,
    Continue,
    FlowIR,
    HandlerCall,
    IfBlock,
    Operation,
    WhileLoop,
)


class RouterGenerator:
    """Generate router functions from Flow IR."""

    def __init__(self, flow_ir: FlowIR):
        self.flow_ir = flow_ir
        self.routers: list[tuple[str, str, str]] = []  # (router_id, docstring, code)

    def generate(self) -> list[tuple[str, str, str]]:
        """
        Generate all router functions.

        Returns:
            List of (router_id, docstring, code) tuples
        """
        self._generate_routers_for_ops(self.flow_ir.operations)
        return self.routers

    def _generate_routers_for_ops(self, ops: list[Operation]):
        """Recursively generate routers for all operations."""
        for op in ops:
            if isinstance(op, IfBlock):
                self._generate_if_router(op)
                # Recurse into branches
                self._generate_routers_for_ops(op.then_ops)
                for _, _, elif_ops in op.elif_blocks:
                    self._generate_routers_for_ops(elif_ops)
                self._generate_routers_for_ops(op.else_ops)

            elif isinstance(op, WhileLoop):
                self._generate_while_router(op)
                # Recurse into body
                self._generate_routers_for_ops(op.body_ops)

    def _generate_if_router(self, if_op: IfBlock):
        """Generate router for if statement."""
        assert if_op.router_id is not None  # Should be set by analyzer
        lines = []

        # Function signature
        lines.append(f"def {if_op.router_id}(envelope: dict) -> dict:")

        # Docstring
        docstring = self._generate_if_docstring(if_op)
        lines.append(f'    """{docstring}"""')

        # Extract envelope components
        lines.append("    p = envelope['payload']")
        lines.append("    r = envelope['route']")
        lines.append("    c = r['current']")
        lines.append("")

        # Generate if/elif/else logic
        lines.append(f"    if {if_op.condition_str}:")
        then_actors = self._collect_actors(if_op.then_ops)
        if then_actors:
            actors_list = ", ".join(self._format_actor(a) for a in then_actors)
            lines.append(f"        r['actors'][c+1:c+1] = [{actors_list}]")
        else:
            lines.append("        pass")

        # Generate elif branches
        for _elif_cond_ast, elif_cond_str, elif_ops in if_op.elif_blocks:
            lines.append(f"    elif {elif_cond_str}:")
            elif_actors = self._collect_actors(elif_ops)
            if elif_actors:
                actors_list = ", ".join(self._format_actor(a) for a in elif_actors)
                lines.append(f"        r['actors'][c+1:c+1] = [{actors_list}]")
            else:
                lines.append("        pass")

        # Generate else branch (if exists)
        if if_op.else_ops:
            lines.append("    else:")
            else_actors = self._collect_actors(if_op.else_ops)
            if else_actors:
                actors_list = ", ".join(self._format_actor(a) for a in else_actors)
                lines.append(f"        r['actors'][c+1:c+1] = [{actors_list}]")
            else:
                lines.append("        pass")

        # Add continuation (what comes after this if block)
        continuation_actors = self._collect_actors(if_op.continuation)
        if continuation_actors:
            lines.append("")
            actors_list = ", ".join(self._format_actor(a) for a in continuation_actors)
            lines.append(f"    r['actors'] += [{actors_list}]")

        lines.append("")
        lines.append("    return envelope")

        code = "\n".join(lines)
        self.routers.append((if_op.router_id, docstring, code))

    def _generate_while_router(self, while_op: WhileLoop):
        """Generate router for while loop."""
        assert while_op.router_id is not None  # Should be set by analyzer
        lines = []

        # Function signature
        lines.append(f"def {while_op.router_id}(envelope: dict) -> dict:")

        # Docstring
        docstring = self._generate_while_docstring(while_op)
        lines.append(f'    """{docstring}"""')

        # Extract envelope components
        lines.append("    p = envelope['payload']")
        lines.append("    r = envelope['route']")
        lines.append("    c = r['current']")
        lines.append("")

        # Generate while condition check
        lines.append(f"    if {while_op.condition_str}:")

        # Loop body actors + loop back to self
        body_actors = self._collect_actors(while_op.body_ops)
        if body_actors:
            # Add body actors + self-loop
            actors_list = ", ".join(self._format_actor(a) for a in body_actors)
            lines.append(f"        r['actors'][c+1:c+1] = [{actors_list}, '{while_op.router_id}']")
        else:
            # Just loop back
            lines.append(f"        r['actors'][c+1:c+1] = ['{while_op.router_id}']")

        lines.append("    else:")

        # Exit loop, jump to continuation
        continuation_actors = self._collect_actors(while_op.continuation)
        if continuation_actors:
            actors_list = ", ".join(self._format_actor(a) for a in continuation_actors)
            lines.append(f"        r['actors'][c+1:c+1] = [{actors_list}]")
        else:
            # No continuation, empty route (will go to happy-end)
            lines.append("        pass")

        lines.append("")
        lines.append("    return envelope")

        code = "\n".join(lines)
        self.routers.append((while_op.router_id, docstring, code))

    def _collect_actors(self, ops: list[Operation]) -> list[str]:
        """
        Collect actor names from operations.

        Returns list of actor names (either handler names or router IDs).
        Stops at control flow (if/while) since they have their own routers.
        """
        actors = []

        for op in ops:
            if isinstance(op, HandlerCall):
                # Generate resolve() call
                actors.append(f'resolve("{op.qualified_name}")')
            elif isinstance(op, IfBlock | WhileLoop):
                # Add router for this control flow
                assert op.router_id is not None  # Should be set by analyzer
                actors.append(op.router_id)
                # Don't recurse - the router will handle branching
                break
            elif isinstance(op, Break):
                # Break handled by parent router
                break
            elif isinstance(op, Continue):
                # Continue handled by parent router
                break
            # Skip Assignment, ClassInstantiation, Return - they don't generate actors

        return actors

    def _format_actor(self, actor: str) -> str:
        """
        Format actor for inclusion in route list.

        Args:
            actor: Actor string, either "resolve(...)" or router_id

        Returns:
            Formatted actor string (quoted if router_id, unquoted if resolve call)
        """
        if actor.startswith("resolve("):
            # It's a resolve() call, don't quote it
            return actor
        else:
            # It's a router ID, quote it
            return f'"{actor}"'

    def _generate_if_docstring(self, if_op: IfBlock) -> str:
        """Generate docstring for if router."""
        lines = []
        lines.append(f"Router for if statement in flow '{self.flow_ir.name}' at line {if_op.line}")
        lines.append("")
        lines.append(f"Absolute line: {if_op.line} (from top of {self.flow_ir.source_file})")
        lines.append(f"Nesting level: {if_op.depth}")
        lines.append("")

        # Describe branches
        lines.append("Branches:")
        then_actors = [a for a in self._collect_actors(if_op.then_ops) if not a.startswith("resolve")]
        if then_actors:
            lines.append(f"  - If {if_op.condition_str}: {', '.join(then_actors)}")
        else:
            lines.append(f"  - If {if_op.condition_str}: ...")

        for _elif_cond_ast, elif_cond_str, elif_ops in if_op.elif_blocks:
            elif_actors = [a for a in self._collect_actors(elif_ops) if not a.startswith("resolve")]
            if elif_actors:
                lines.append(f"  - Else if {elif_cond_str}: {', '.join(elif_actors)}")
            else:
                lines.append(f"  - Else if {elif_cond_str}: ...")

        if if_op.else_ops:
            else_actors = [a for a in self._collect_actors(if_op.else_ops) if not a.startswith("resolve")]
            if else_actors:
                lines.append(f"  - Else: {', '.join(else_actors)}")
            else:
                lines.append("  - Else: ...")

        return "\n    ".join(lines)

    def _generate_while_docstring(self, while_op: WhileLoop) -> str:
        """Generate docstring for while router."""
        lines = []
        lines.append(f"Router for while loop at line {while_op.line} in flow '{self.flow_ir.name}'")
        lines.append("")
        lines.append(f"Absolute line: {while_op.line} (from top of {self.flow_ir.source_file})")
        lines.append(f"Nesting level: {while_op.depth}")
        lines.append("")

        # Describe loop
        lines.append(f"Condition: {while_op.condition_str}")

        body_actors = [a for a in self._collect_actors(while_op.body_ops) if not a.startswith("resolve")]
        if body_actors:
            lines.append(f"Body actors: {', '.join(body_actors)}")
        else:
            lines.append("Body: (empty)")

        if while_op.has_break:
            lines.append("Contains break statement")
        if while_op.has_continue:
            lines.append("Contains continue statement")

        return "\n    ".join(lines)
