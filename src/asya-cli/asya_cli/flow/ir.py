"""
Intermediate Representation (IR) for Flow DSL.

Represents the flow as a sequence of operations that can be analyzed
and transformed into router code.
"""

import ast
from dataclasses import dataclass, field
from typing import Any, List, Optional


@dataclass
class Operation:
    """Base class for all flow operations."""

    line: int
    col: int


@dataclass
class HandlerCall(Operation):
    """
    Handler call: p = handler(p)

    Attributes:
        func_name: Function/method name from code (e.g., "processor" or "processor.process")
        qualified_name: Full qualified name (e.g., "my_module.ImageProcessor.process")
        target: Variable being assigned to (always "p" in valid flows)
    """

    func_name: str
    qualified_name: str
    target: str = "p"


@dataclass
class Assignment(Operation):
    """
    Payload mutation: p["key"] = value

    Attributes:
        target: The variable being assigned (must be "p")
        key: The key being assigned (for p["key"] = value)
        value_ast: AST node of the value expression
        value_str: String representation of value for codegen
    """

    target: str
    key: Optional[str]
    value_ast: ast.expr
    value_str: str


@dataclass
class IfBlock(Operation):
    """
    If/elif/else control flow.

    Attributes:
        condition: AST node of the condition
        condition_str: String representation for codegen
        then_ops: Operations in the if branch
        elif_blocks: List of (condition_ast, condition_str, operations) for elif branches
        else_ops: Operations in the else branch
        router_id: Assigned router ID (set by analyzer)
        continuation: Operations that come after this if block (set by analyzer)
        depth: Nesting depth (set by analyzer)
    """

    condition: ast.expr
    condition_str: str
    then_ops: List[Operation]
    elif_blocks: List[tuple[ast.expr, str, List[Operation]]] = field(default_factory=list)
    else_ops: List[Operation] = field(default_factory=list)
    router_id: Optional[str] = None
    continuation: List[Operation] = field(default_factory=list)
    depth: int = 0


@dataclass
class WhileLoop(Operation):
    """
    While loop.

    Attributes:
        condition: AST node of the condition
        condition_str: String representation for codegen
        body_ops: Operations in the loop body
        router_id: Assigned router ID (set by analyzer)
        continuation: Operations that come after this loop (set by analyzer)
        depth: Nesting depth (set by analyzer)
        has_break: Whether loop contains break statement (set by analyzer)
        has_continue: Whether loop contains continue statement (set by analyzer)
    """

    condition: ast.expr
    condition_str: str
    body_ops: List[Operation]
    router_id: Optional[str] = None
    continuation: List[Operation] = field(default_factory=list)
    depth: int = 0
    has_break: bool = False
    has_continue: bool = False


@dataclass
class Break(Operation):
    """Break from loop."""

    pass


@dataclass
class Continue(Operation):
    """Continue to next iteration."""

    pass


@dataclass
class Return(Operation):
    """
    Return statement.

    Attributes:
        value: Variable being returned (must be "p" in valid flows)
    """

    value: str = "p"


@dataclass
class ClassInstantiation(Operation):
    """
    Class instantiation: var = ClassName(args)

    Attributes:
        var_name: Variable name (e.g., "processor")
        class_name: Class name from code (e.g., "ImageProcessor")
        qualified_name: Full qualified name (e.g., "my_module.ImageProcessor")
        args: Constructor arguments (AST nodes)
        kwargs: Constructor keyword arguments (AST nodes)
    """

    var_name: str
    class_name: str
    qualified_name: str
    args: List[ast.expr] = field(default_factory=list)
    kwargs: dict[str, ast.expr] = field(default_factory=dict)


@dataclass
class FlowIR:
    """
    Complete flow representation.

    Attributes:
        name: Flow function name
        param_name: Parameter name (usually "p")
        operations: Sequential operations
        source_file: Source file path
        lineno: Function definition line number
        imports: Import statements (AST nodes)
        class_instances: Map of variable names to qualified class names
    """

    name: str
    param_name: str
    operations: List[Operation]
    source_file: str
    lineno: int
    imports: List[ast.Import | ast.ImportFrom] = field(default_factory=list)
    class_instances: dict[str, str] = field(default_factory=dict)
