"""
Control flow analyzer for Flow DSL.

Analyzes control flow, assigns router IDs, detects infinite loops.
"""

import ast

from asya_cli.flow.ir import (
    Assignment,
    Break,
    Continue,
    FlowIR,
    IfBlock,
    Operation,
    WhileLoop,
)


class ControlFlowAnalyzer:
    """
    Analyze control flow and assign router IDs.

    Uses stack-based approach to track nesting depth and continuation.
    """

    def __init__(self, flow_name: str, check_infinite_loops: bool = True):
        self.flow_name = flow_name
        self.check_infinite_loops = check_infinite_loops
        self.warnings: list[str] = []
        self.loop_stack: list[WhileLoop] = []  # Track active loops for break/continue

    def analyze(self, flow_ir: FlowIR) -> FlowIR:
        """
        Analyze flow and assign router IDs.

        Args:
            flow_ir: Flow intermediate representation

        Returns:
            Updated FlowIR with router IDs assigned
        """
        flow_ir.operations = self._analyze_ops(flow_ir.operations, depth=0, parent_continuation=[])
        return flow_ir

    def _analyze_ops(self, ops: list[Operation], depth: int, parent_continuation: list[Operation]) -> list[Operation]:
        """
        Analyze operations recursively, assigning router IDs and continuations.

        Args:
            ops: List of operations
            depth: Current nesting depth

        Returns:
            Updated operations with router IDs
        """
        result: list[Operation] = []
        i = 0

        while i < len(ops):
            op = ops[i]

            if isinstance(op, IfBlock):
                # Assign router ID
                op.router_id = self._gen_router_id("if", op.line)
                op.depth = depth

                # Determine continuation (local + parent)
                local_continuation = ops[i + 1 :]
                op.continuation = local_continuation + parent_continuation

                # Analyze branches recursively, passing down the continuation
                op.then_ops = self._analyze_ops(op.then_ops, depth + 1, op.continuation)

                # Analyze elif branches
                new_elif_blocks = []
                for cond, cond_str, elif_ops in op.elif_blocks:
                    analyzed_elif_ops = self._analyze_ops(elif_ops, depth + 1, op.continuation)
                    new_elif_blocks.append((cond, cond_str, analyzed_elif_ops))
                op.elif_blocks = new_elif_blocks

                # Analyze else branch
                op.else_ops = self._analyze_ops(op.else_ops, depth + 1, op.continuation)

                result.append(op)

            elif isinstance(op, WhileLoop):
                # Assign router ID
                op.router_id = self._gen_router_id("while", op.line)
                op.depth = depth

                # Determine continuation (local + parent)
                local_continuation = ops[i + 1 :]
                op.continuation = local_continuation + parent_continuation

                # Push loop onto stack for break/continue tracking
                self.loop_stack.append(op)

                # Analyze body recursively, passing continuation for break statements
                op.body_ops = self._analyze_ops(op.body_ops, depth + 1, op.continuation)

                # Pop loop from stack
                self.loop_stack.pop()

                # Check for break/continue in body
                op.has_break = self._has_break(op.body_ops)
                op.has_continue = self._has_continue(op.body_ops)

                # Check for infinite loop
                if self.check_infinite_loops:
                    warning = self._check_infinite_loop(op)
                    if warning:
                        self.warnings.append(warning)

                result.append(op)

            elif isinstance(op, Break | Continue):
                # Validate that we're inside a loop
                if not self.loop_stack:
                    # This should have been caught by parser
                    raise RuntimeError(
                        f"Internal Compiler Error: '{type(op).__name__}' statement outside of a loop at line {op.line}. "
                        "This should have been caught by the parser."
                    )
                result.append(op)

            else:
                result.append(op)

            i += 1

        return result

    def _gen_router_id(self, stmt_type: str, line: int) -> str:
        """
        Generate router ID with flow name prefix.

        Args:
            stmt_type: Type of statement ("if" or "while")
            line: Line number in source

        Returns:
            Router ID like "my_flow_line_7_if"
        """
        return f"{self.flow_name}_line_{line}_{stmt_type}"

    def _has_break(self, ops: list[Operation]) -> bool:
        """Check if operations contain break statement."""
        for op in ops:
            if isinstance(op, Break):
                return True
            elif isinstance(op, IfBlock):
                if self._has_break(op.then_ops):
                    return True
                for _, _, elif_ops in op.elif_blocks:
                    if self._has_break(elif_ops):
                        return True
                if self._has_break(op.else_ops):
                    return True
            elif isinstance(op, WhileLoop):
                # Don't recurse into nested loops
                pass
        return False

    def _has_continue(self, ops: list[Operation]) -> bool:
        """Check if operations contain continue statement."""
        for op in ops:
            if isinstance(op, Continue):
                return True
            elif isinstance(op, IfBlock):
                if self._has_continue(op.then_ops):
                    return True
                for _, _, elif_ops in op.elif_blocks:
                    if self._has_continue(elif_ops):
                        return True
                if self._has_continue(op.else_ops):
                    return True
            elif isinstance(op, WhileLoop):
                # Don't recurse into nested loops
                pass
        return False

    def _check_infinite_loop(self, while_op: WhileLoop) -> str | None:
        """
        Check for potential infinite loops.

        Detects if loop condition variables are never modified in loop body.

        Args:
            while_op: While loop operation

        Returns:
            Warning message if potential infinite loop detected
        """
        # Extract variables from condition
        condition_vars = self._extract_variables(while_op.condition)

        if not condition_vars:
            # Can't analyze, skip
            return None

        # Check if any condition variable is modified in loop body
        modified_vars = self._extract_modified_vars(while_op.body_ops)

        # Check intersection
        if not (condition_vars & modified_vars):
            sorted_vars = sorted(condition_vars)
            return (
                f"Warning: Potential infinite loop at line {while_op.line}\n"
                f"  Loop condition uses variables: {sorted_vars}\n"
                f"  But none are modified in loop body.\n"
                f"  Suggestion: Add mutations like p['{sorted_vars[0]}'] += 1"
            )

        return None

    def _extract_variables(self, node: ast.expr) -> set[str]:
        """
        Extract variables referenced in an expression.

        For p["count"] < 5, extracts {"count"}
        """
        variables = set()

        for child in ast.walk(node):
            # Look for p["key"] patterns
            if (
                isinstance(child, ast.Subscript)
                and isinstance(child.value, ast.Name)
                and child.value.id == "p"
                and isinstance(child.slice, ast.Constant)
                and isinstance(child.slice.value, str)
            ):
                variables.add(child.slice.value)

        return variables

    def _extract_modified_vars(self, ops: list[Operation]) -> set[str]:
        """Extract variables that are modified in operations."""
        modified = set()

        for op in ops:
            if isinstance(op, Assignment) and op.key:
                modified.add(op.key)
            elif isinstance(op, IfBlock):
                # Variables modified in any branch count
                modified.update(self._extract_modified_vars(op.then_ops))
                for _, _, elif_ops in op.elif_blocks:
                    modified.update(self._extract_modified_vars(elif_ops))
                modified.update(self._extract_modified_vars(op.else_ops))
            elif isinstance(op, WhileLoop):
                # Variables modified in nested loops count
                modified.update(self._extract_modified_vars(op.body_ops))

        return modified
