"""Unit tests for operation grouper."""

from asya_cli.flow.grouper import OperationGrouper
from asya_cli.flow.ir import ActorCall, Break, Condition, Continue, IROperation, Mutation, Return, WhileLoop


class TestRouterStructure:
    """Test basic router generation and structure."""

    def test_empty_flow_creates_start_and_end(self):
        ops: list[IROperation] = [Return(lineno=1)]
        grouper = OperationGrouper("test_flow", ops)
        routers = grouper.group()

        assert len(routers) == 2
        assert routers[0].name == "start_test_flow"
        assert routers[1].name == "end_test_flow"

    def test_start_router_has_correct_structure(self):
        ops = [ActorCall(lineno=1, name="handler"), Return(lineno=2)]
        grouper = OperationGrouper("my_flow", ops)
        routers = grouper.group()

        start = routers[0]
        assert start.name.startswith("start_")
        assert start.lineno == 0
        assert start.condition is None
        assert len(start.mutations) == 0
        assert "handler" in start.true_branch_actors
        assert "end_my_flow" in start.true_branch_actors

    def test_end_router_has_correct_structure(self):
        ops: list[IROperation] = [Return(lineno=1)]
        grouper = OperationGrouper("my_flow", ops)
        routers = grouper.group()

        end = routers[-1]
        assert end.name.startswith("end_")
        assert end.condition is None
        assert len(end.mutations) == 0
        assert len(end.true_branch_actors) == 0
        assert len(end.false_branch_actors) == 0


class TestSimpleFlows:
    """Test simple sequential flows."""

    def test_single_handler_no_intermediate_router(self):
        ops = [ActorCall(lineno=1, name="handler"), Return(lineno=2)]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        assert len(routers) == 2
        start, end = routers
        assert "handler" in start.true_branch_actors
        assert "end_flow" in start.true_branch_actors

    def test_multiple_sequential_handlers(self):
        ops = [
            ActorCall(lineno=1, name="handler_a"),
            ActorCall(lineno=2, name="handler_b"),
            ActorCall(lineno=3, name="handler_c"),
            Return(lineno=4),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        start = routers[0]
        assert "handler_a" in start.true_branch_actors
        assert "handler_b" in start.true_branch_actors
        assert "handler_c" in start.true_branch_actors
        assert "end_flow" in start.true_branch_actors

    def test_mutations_only_creates_router(self):
        ops = [Mutation(lineno=1, code='p["x"] = 1'), Mutation(lineno=2, code='p["y"] = 2'), Return(lineno=3)]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        assert len(routers) == 3
        router = next(r for r in routers if r.name.startswith("router_"))
        assert len(router.mutations) == 2
        assert router.condition is None

    def test_mutations_with_handler_creates_router(self):
        ops = [
            Mutation(lineno=1, code='p["x"] = 1'),
            ActorCall(lineno=2, name="handler"),
            Return(lineno=3),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        router = next(r for r in routers if r.name.startswith("router_"))
        assert len(router.mutations) == 1
        assert "handler" in router.true_branch_actors
        assert "end_flow" in router.true_branch_actors

    def test_multiple_mutations_grouped_together(self):
        ops = [
            Mutation(lineno=1, code='p["a"] = 1'),
            Mutation(lineno=2, code='p["b"] = 2'),
            Mutation(lineno=3, code='p["c"] = 3'),
            ActorCall(lineno=4, name="handler"),
            Return(lineno=5),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        router = next(r for r in routers if r.name.startswith("router_"))
        assert len(router.mutations) == 3


class TestConditionals:
    """Test conditional branching."""

    def test_simple_if_else_creates_router(self):
        ops = [
            Condition(
                lineno=1,
                test='p["x"]',
                true_branch=[ActorCall(lineno=2, name="handler_a")],
                false_branch=[ActorCall(lineno=3, name="handler_b")],
            ),
            Return(lineno=4),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        cond_routers = [r for r in routers if r.condition is not None]
        assert len(cond_routers) == 1

        router = cond_routers[0]
        assert router.name.endswith("_if")
        assert router.condition is not None
        assert router.condition.test == 'p["x"]'
        assert "handler_a" in router.true_branch_actors
        assert "handler_b" in router.false_branch_actors

    def test_if_without_else_has_empty_false_branch(self):
        ops = [
            Condition(
                lineno=1,
                test='p["x"]',
                true_branch=[ActorCall(lineno=2, name="handler")],
                false_branch=[],
            ),
            Return(lineno=3),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        cond_router = next(r for r in routers if r.condition is not None)
        assert len(cond_router.true_branch_actors) > 0
        assert "end_flow" in cond_router.false_branch_actors

    def test_both_branches_converge_to_same_continuation(self):
        ops = [
            Condition(
                lineno=1,
                test='p["x"]',
                true_branch=[ActorCall(lineno=2, name="handler_a")],
                false_branch=[ActorCall(lineno=3, name="handler_b")],
            ),
            ActorCall(lineno=4, name="final_handler"),
            Return(lineno=5),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        cond_router = next(r for r in routers if r.condition is not None)
        assert "final_handler" in cond_router.true_branch_actors
        assert "final_handler" in cond_router.false_branch_actors
        assert "end_flow" in cond_router.true_branch_actors
        assert "end_flow" in cond_router.false_branch_actors

    def test_mutations_before_conditional(self):
        ops = [
            Mutation(lineno=1, code='p["init"] = True'),
            Condition(
                lineno=2,
                test='p["x"]',
                true_branch=[ActorCall(lineno=3, name="handler_a")],
                false_branch=[ActorCall(lineno=4, name="handler_b")],
            ),
            Return(lineno=5),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        cond_router = next(r for r in routers if r.condition is not None)
        assert len(cond_router.mutations) == 1
        assert cond_router.mutations[0].code == 'p["init"] = True'

    def test_mutations_in_branches(self):
        ops = [
            Condition(
                lineno=1,
                test='p["x"]',
                true_branch=[
                    Mutation(lineno=2, code='p["branch"] = "A"'),
                    ActorCall(lineno=3, name="handler_a"),
                ],
                false_branch=[
                    Mutation(lineno=4, code='p["branch"] = "B"'),
                    ActorCall(lineno=5, name="handler_b"),
                ],
            ),
            Return(lineno=6),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        branch_routers = [r for r in routers if r.name.startswith("router_") and len(r.mutations) > 0]
        assert len(branch_routers) >= 2


class TestNestedConditionals:
    """Test nested conditional structures."""

    def test_nested_if_in_true_branch(self):
        ops = [
            Condition(
                lineno=1,
                test='p["outer"]',
                true_branch=[
                    Condition(
                        lineno=2,
                        test='p["inner"]',
                        true_branch=[ActorCall(lineno=3, name="handler_a")],
                        false_branch=[ActorCall(lineno=4, name="handler_b")],
                    )
                ],
                false_branch=[ActorCall(lineno=5, name="handler_c")],
            ),
            Return(lineno=6),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        cond_routers = [r for r in routers if r.condition is not None]
        assert len(cond_routers) == 2

    def test_nested_if_in_false_branch(self):
        ops = [
            Condition(
                lineno=1,
                test='p["outer"]',
                true_branch=[ActorCall(lineno=2, name="handler_a")],
                false_branch=[
                    Condition(
                        lineno=3,
                        test='p["inner"]',
                        true_branch=[ActorCall(lineno=4, name="handler_b")],
                        false_branch=[ActorCall(lineno=5, name="handler_c")],
                    )
                ],
            ),
            Return(lineno=6),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        cond_routers = [r for r in routers if r.condition is not None]
        assert len(cond_routers) == 2

    def test_deeply_nested_conditionals(self):
        ops = [
            Condition(
                lineno=1,
                test='p["l1"]',
                true_branch=[
                    Condition(
                        lineno=2,
                        test='p["l2"]',
                        true_branch=[
                            Condition(
                                lineno=3,
                                test='p["l3"]',
                                true_branch=[ActorCall(lineno=4, name="handler_deep")],
                                false_branch=[],
                            )
                        ],
                        false_branch=[],
                    )
                ],
                false_branch=[],
            ),
            Return(lineno=5),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        cond_routers = [r for r in routers if r.condition is not None]
        assert len(cond_routers) == 3

    def test_multiple_conditionals_sequential(self):
        ops = [
            Condition(
                lineno=1,
                test='p["check1"]',
                true_branch=[ActorCall(lineno=2, name="handler_1")],
                false_branch=[],
            ),
            Condition(
                lineno=3,
                test='p["check2"]',
                true_branch=[ActorCall(lineno=4, name="handler_2")],
                false_branch=[],
            ),
            Return(lineno=5),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        cond_routers = [r for r in routers if r.condition is not None]
        assert len(cond_routers) == 2


class TestConvergence:
    """Test branch convergence behavior."""

    def test_simple_convergence_to_next_handler(self):
        ops = [
            ActorCall(lineno=1, name="setup"),
            Condition(
                lineno=2,
                test='p["x"]',
                true_branch=[ActorCall(lineno=3, name="handler_a")],
                false_branch=[ActorCall(lineno=4, name="handler_b")],
            ),
            ActorCall(lineno=5, name="finalize"),
            Return(lineno=6),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        cond_router = next(r for r in routers if r.condition is not None)
        assert "finalize" in cond_router.true_branch_actors
        assert "finalize" in cond_router.false_branch_actors

    def test_convergence_to_end(self):
        ops = [
            Condition(
                lineno=1,
                test='p["x"]',
                true_branch=[ActorCall(lineno=2, name="handler_a")],
                false_branch=[ActorCall(lineno=3, name="handler_b")],
            ),
            Return(lineno=4),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        cond_router = next(r for r in routers if r.condition is not None)
        assert "end_flow" in cond_router.true_branch_actors
        assert "end_flow" in cond_router.false_branch_actors

    def test_nested_convergence_propagation(self):
        ops = [
            Condition(
                lineno=1,
                test='p["outer"]',
                true_branch=[
                    Condition(
                        lineno=2,
                        test='p["inner"]',
                        true_branch=[ActorCall(lineno=3, name="handler_a")],
                        false_branch=[ActorCall(lineno=4, name="handler_b")],
                    )
                ],
                false_branch=[ActorCall(lineno=5, name="handler_c")],
            ),
            ActorCall(lineno=6, name="final"),
            Return(lineno=7),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        outer_router = next(r for r in routers if r.condition is not None and 'p["outer"]' in r.condition.test)
        assert "final" in outer_router.true_branch_actors or any("final" in r.true_branch_actors for r in routers)


class TestEarlyReturn:
    """Test early return patterns."""

    def test_early_return_in_true_branch(self):
        ops = [
            Condition(
                lineno=1,
                test='p["early"]',
                true_branch=[Return(lineno=2)],
                false_branch=[ActorCall(lineno=3, name="handler")],
            ),
            Return(lineno=4),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        cond_router = next(r for r in routers if r.condition is not None)
        assert "end_flow" in cond_router.true_branch_actors
        assert "handler" in cond_router.false_branch_actors

    def test_early_return_in_false_branch(self):
        ops = [
            Condition(
                lineno=1,
                test='p["continue"]',
                true_branch=[ActorCall(lineno=2, name="handler")],
                false_branch=[Return(lineno=3)],
            ),
            Return(lineno=4),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        cond_router = next(r for r in routers if r.condition is not None)
        assert "handler" in cond_router.true_branch_actors
        assert "end_flow" in cond_router.false_branch_actors

    def test_early_return_in_both_branches(self):
        ops = [
            Condition(
                lineno=1,
                test='p["x"]',
                true_branch=[Return(lineno=2)],
                false_branch=[Return(lineno=3)],
            ),
            ActorCall(lineno=4, name="unreachable"),
            Return(lineno=5),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        cond_router = next(r for r in routers if r.condition is not None)
        assert "end_flow" in cond_router.true_branch_actors
        assert "end_flow" in cond_router.false_branch_actors


class TestEmptyBranches:
    """Test handling of empty branches."""

    def test_empty_true_branch(self):
        ops = [
            Condition(
                lineno=1,
                test='p["x"]',
                true_branch=[],
                false_branch=[ActorCall(lineno=2, name="handler")],
            ),
            Return(lineno=3),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        cond_router = next(r for r in routers if r.condition is not None)
        assert "end_flow" in cond_router.true_branch_actors

    def test_empty_false_branch(self):
        ops = [
            Condition(
                lineno=1,
                test='p["x"]',
                true_branch=[ActorCall(lineno=2, name="handler")],
                false_branch=[],
            ),
            Return(lineno=3),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        cond_router = next(r for r in routers if r.condition is not None)
        assert "end_flow" in cond_router.false_branch_actors

    def test_both_branches_empty(self):
        ops = [
            Condition(
                lineno=1,
                test='p["x"]',
                true_branch=[],
                false_branch=[],
            ),
            ActorCall(lineno=2, name="handler"),
            Return(lineno=3),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        cond_router = next(r for r in routers if r.condition is not None)
        assert "handler" in cond_router.true_branch_actors
        assert "handler" in cond_router.false_branch_actors


class TestComplexPatterns:
    """Test complex real-world patterns."""

    def test_mutations_handlers_conditionals_mixed(self):
        ops = [
            Mutation(lineno=1, code='p["status"] = "init"'),
            ActorCall(lineno=2, name="setup"),
            Condition(
                lineno=3,
                test='p["type"] == "A"',
                true_branch=[
                    Mutation(lineno=4, code='p["branch"] = "A"'),
                    ActorCall(lineno=5, name="handler_a"),
                ],
                false_branch=[
                    Mutation(lineno=6, code='p["branch"] = "B"'),
                    ActorCall(lineno=7, name="handler_b"),
                ],
            ),
            ActorCall(lineno=8, name="finalize"),
            Mutation(lineno=9, code='p["status"] = "done"'),
            Return(lineno=10),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        assert len(routers) >= 3
        assert any(r.condition is not None for r in routers)
        assert any(len(r.mutations) > 0 for r in routers)

    def test_multiple_layers_of_nesting(self):
        ops = [
            Condition(
                lineno=1,
                test='p["l1"] == "A"',
                true_branch=[
                    Condition(
                        lineno=2,
                        test='p["l2"] == "X"',
                        true_branch=[ActorCall(lineno=3, name="handler_ax")],
                        false_branch=[ActorCall(lineno=4, name="handler_ay")],
                    )
                ],
                false_branch=[
                    Condition(
                        lineno=5,
                        test='p["l2"] == "X"',
                        true_branch=[ActorCall(lineno=6, name="handler_bx")],
                        false_branch=[ActorCall(lineno=7, name="handler_by")],
                    )
                ],
            ),
            ActorCall(lineno=8, name="final"),
            Return(lineno=9),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        cond_routers = [r for r in routers if r.condition is not None]
        assert len(cond_routers) == 3

        all_branches = []
        for r in cond_routers:
            all_branches.extend(r.true_branch_actors)
            all_branches.extend(r.false_branch_actors)

        assert any("final" in str(branch) for branch in all_branches)

    def test_sequential_mutations_between_handlers(self):
        ops = [
            ActorCall(lineno=1, name="handler_1"),
            Mutation(lineno=2, code='p["step"] = 1'),
            Mutation(lineno=3, code='p["timestamp"] = 123'),
            ActorCall(lineno=4, name="handler_2"),
            Mutation(lineno=5, code='p["step"] = 2'),
            ActorCall(lineno=6, name="handler_3"),
            Return(lineno=7),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        mutation_routers = [r for r in routers if len(r.mutations) > 0]
        assert len(mutation_routers) >= 2


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_only_return_statement(self):
        ops: list[IROperation] = [Return(lineno=1)]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        assert len(routers) == 2
        start, end = routers
        assert "end_flow" in start.true_branch_actors

    def test_single_mutation_only(self):
        ops = [Mutation(lineno=1, code='p["x"] = 1'), Return(lineno=2)]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        router = next(r for r in routers if r.name.startswith("router_"))
        assert len(router.mutations) == 1

    def test_convergence_counter_increments(self):
        ops = [
            Condition(lineno=1, test='p["x"]', true_branch=[], false_branch=[]),
            Condition(lineno=2, test='p["y"]', true_branch=[], false_branch=[]),
            Condition(lineno=3, test='p["z"]', true_branch=[], false_branch=[]),
            Return(lineno=4),
        ]
        grouper = OperationGrouper("flow", ops)
        grouper.group()

        assert grouper.convergence_counter == 3

    def test_flow_name_in_router_names(self):
        ops = [ActorCall(lineno=1, name="handler"), Return(lineno=2)]
        grouper = OperationGrouper("custom_flow_name", ops)
        routers = grouper.group()

        assert routers[0].name == "start_custom_flow_name"
        assert routers[-1].name == "end_custom_flow_name"

    def test_lineno_preserved_in_routers(self):
        ops = [
            Mutation(lineno=10, code='p["x"] = 1'),
            Condition(
                lineno=20,
                test='p["y"]',
                true_branch=[ActorCall(lineno=21, name="handler_a")],
                false_branch=[ActorCall(lineno=22, name="handler_b")],
            ),
            Return(lineno=30),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        mutation_router = next(r for r in routers if len(r.mutations) > 0)
        assert mutation_router.lineno == 20  # Lineno from condition, not mutation

        cond_router = next(r for r in routers if r.condition is not None)
        assert cond_router.lineno == 20

    def test_no_duplicate_convergence_actors(self):
        ops = [
            Condition(
                lineno=1,
                test='p["x"]',
                true_branch=[ActorCall(lineno=2, name="handler_a")],
                false_branch=[ActorCall(lineno=3, name="handler_b")],
            ),
            ActorCall(lineno=4, name="final"),
            Return(lineno=5),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        cond_router = next(r for r in routers if r.condition is not None)
        true_final_count = cond_router.true_branch_actors.count("final")
        false_final_count = cond_router.false_branch_actors.count("final")

        assert true_final_count == 1
        assert false_final_count == 1


class TestWhileLoopGrouping:
    """Test while loop router generation."""

    def test_simple_while_creates_condition_and_loop_back_routers(self):
        ops = [
            WhileLoop(
                lineno=3,
                test='p["i"] < 10',
                body=[ActorCall(lineno=4, name="handler")],
            ),
            Return(lineno=5),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        # Should have: start, while_condition, loop_back, end
        loop_back_routers = [r for r in routers if r.is_loop_back]
        assert len(loop_back_routers) == 1

        cond_routers = [r for r in routers if r.condition is not None and "while" in r.name]
        assert len(cond_routers) == 1

        cond_router = cond_routers[0]
        assert cond_router.condition is not None
        assert cond_router.condition.test == 'p["i"] < 10'
        assert "handler" in cond_router.true_branch_actors
        assert loop_back_routers[0].name in cond_router.true_branch_actors

    def test_while_true_no_condition_router(self):
        ops = [
            WhileLoop(
                lineno=3,
                test=None,
                body=[
                    ActorCall(lineno=4, name="handler"),
                    Condition(
                        lineno=5,
                        test='p["done"]',
                        true_branch=[Break(lineno=6)],
                        false_branch=[],
                    ),
                ],
            ),
            Return(lineno=7),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        # while True should NOT create a condition router
        while_cond_routers = [r for r in routers if r.condition is not None and "while" in r.name]
        assert len(while_cond_routers) == 0

        # But should create a loop-back router
        loop_back_routers = [r for r in routers if r.is_loop_back]
        assert len(loop_back_routers) == 1

        # Loop-back re-inserts body actors + itself
        lb = loop_back_routers[0]
        assert lb.name in lb.true_branch_actors

    def test_while_condition_false_goes_to_continuation(self):
        ops = [
            WhileLoop(
                lineno=3,
                test='p["i"] < 10',
                body=[ActorCall(lineno=4, name="handler")],
            ),
            ActorCall(lineno=5, name="finalize"),
            Return(lineno=6),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        cond_router = next(r for r in routers if r.condition is not None and "while" in r.name)
        # False branch should contain finalize + end
        assert "finalize" in cond_router.false_branch_actors

    def test_while_loop_back_re_inserts_condition(self):
        ops = [
            WhileLoop(
                lineno=3,
                test='p["i"] < 10',
                body=[ActorCall(lineno=4, name="handler")],
            ),
            Return(lineno=5),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        loop_back = next(r for r in routers if r.is_loop_back)
        cond_router = next(r for r in routers if r.condition is not None and "while" in r.name)

        # Loop-back should re-insert the condition router
        assert cond_router.name in loop_back.true_branch_actors

    def test_while_with_break_goes_to_continuation(self):
        ops = [
            WhileLoop(
                lineno=3,
                test='p["i"] < 10',
                body=[
                    ActorCall(lineno=4, name="handler"),
                    Condition(
                        lineno=5,
                        test='p["stop"]',
                        true_branch=[Break(lineno=6)],
                        false_branch=[],
                    ),
                ],
            ),
            ActorCall(lineno=7, name="finalize"),
            Return(lineno=8),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        # The break's if-condition router should route to finalize on the true branch
        break_cond = next(r for r in routers if r.condition is not None and r.condition.test == 'p["stop"]')
        assert "finalize" in break_cond.true_branch_actors

    def test_while_with_continue_goes_to_loop_back(self):
        ops = [
            WhileLoop(
                lineno=3,
                test='p["i"] < 10',
                body=[
                    Mutation(lineno=4, code='p["i"] += 1'),
                    Condition(
                        lineno=5,
                        test='p["skip"]',
                        true_branch=[Continue(lineno=6)],
                        false_branch=[],
                    ),
                    ActorCall(lineno=7, name="handler"),
                ],
            ),
            Return(lineno=8),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        loop_back = next(r for r in routers if r.is_loop_back)

        # Continue's if-condition should route to loop_back on the true branch
        skip_cond = next(r for r in routers if r.condition is not None and r.condition.test == 'p["skip"]')
        assert loop_back.name in skip_cond.true_branch_actors

    def test_while_with_mutations_before_loop(self):
        ops = [
            Mutation(lineno=2, code='p["i"] = 0'),
            WhileLoop(
                lineno=3,
                test='p["i"] < 10',
                body=[
                    Mutation(lineno=4, code='p["i"] += 1'),
                    ActorCall(lineno=5, name="handler"),
                ],
            ),
            Return(lineno=6),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        # Mutation before while should be in the while condition router's mutations
        cond_router = next(r for r in routers if r.condition is not None and "while" in r.name)
        assert len(cond_router.mutations) == 1
        assert cond_router.mutations[0].code == 'p["i"] = 0'

    def test_while_body_mutations_grouped(self):
        ops = [
            WhileLoop(
                lineno=3,
                test='p["i"] < 10',
                body=[
                    Mutation(lineno=4, code='p["i"] += 1'),
                    Mutation(lineno=5, code='p["sum"] += p["i"]'),
                    ActorCall(lineno=6, name="handler"),
                ],
            ),
            Return(lineno=7),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        # There should be a seq router inside the body with the grouped mutations
        seq_routers = [r for r in routers if "_seq" in r.name]
        assert len(seq_routers) >= 1
        body_seq = seq_routers[0]
        assert len(body_seq.mutations) == 2

    def test_while_with_handler_before_and_after(self):
        ops = [
            ActorCall(lineno=1, name="init"),
            WhileLoop(
                lineno=3,
                test='p["i"] < 10',
                body=[ActorCall(lineno=4, name="process")],
            ),
            ActorCall(lineno=5, name="finalize"),
            Return(lineno=6),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        start = routers[0]
        assert "init" in start.true_branch_actors

        cond = next(r for r in routers if r.condition is not None and "while" in r.name)
        assert "process" in cond.true_branch_actors
        assert "finalize" in cond.false_branch_actors

    def test_nested_while_loops(self):
        ops = [
            WhileLoop(
                lineno=3,
                test='p["i"] < 10',
                body=[
                    WhileLoop(
                        lineno=5,
                        test='p["j"] < 5',
                        body=[ActorCall(lineno=6, name="handler")],
                    ),
                ],
            ),
            Return(lineno=7),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        # Should have two condition routers and two loop-back routers
        cond_routers = [r for r in routers if r.condition is not None and "while" in r.name]
        loop_back_routers = [r for r in routers if r.is_loop_back]
        assert len(cond_routers) == 2
        assert len(loop_back_routers) == 2

    def test_while_loop_counter_increments(self):
        ops = [
            WhileLoop(
                lineno=3,
                test='p["i"] < 10',
                body=[ActorCall(lineno=4, name="handler_a")],
            ),
            WhileLoop(
                lineno=6,
                test='p["j"] < 5',
                body=[ActorCall(lineno=7, name="handler_b")],
            ),
            Return(lineno=8),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        loop_back_routers = [r for r in routers if r.is_loop_back]
        assert len(loop_back_routers) == 2
        assert loop_back_routers[0].name != loop_back_routers[1].name

    def test_while_with_if_inside_body(self):
        ops = [
            WhileLoop(
                lineno=3,
                test='p["i"] < 10',
                body=[
                    Condition(
                        lineno=4,
                        test='p["type"] == "A"',
                        true_branch=[ActorCall(lineno=5, name="handler_a")],
                        false_branch=[ActorCall(lineno=6, name="handler_b")],
                    ),
                ],
            ),
            Return(lineno=7),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        # Should have while condition + if condition + loop_back
        if_routers = [r for r in routers if r.condition is not None and "_if" in r.name]
        assert len(if_routers) == 1
        if_router = if_routers[0]
        assert "handler_a" in if_router.true_branch_actors
        assert "handler_b" in if_router.false_branch_actors

    def test_while_true_with_only_break(self):
        ops = [
            WhileLoop(
                lineno=3,
                test=None,
                body=[
                    Condition(
                        lineno=4,
                        test='p["done"]',
                        true_branch=[Break(lineno=5)],
                        false_branch=[],
                    ),
                ],
            ),
            Return(lineno=6),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        done_cond = next(r for r in routers if r.condition is not None and r.condition.test == 'p["done"]')
        # True branch (break) should go to end_flow
        assert "end_flow" in done_cond.true_branch_actors

    def test_while_with_return_in_body(self):
        ops = [
            WhileLoop(
                lineno=3,
                test=None,
                body=[
                    ActorCall(lineno=4, name="handler"),
                    Condition(
                        lineno=5,
                        test='p["final"]',
                        true_branch=[Return(lineno=6)],
                        false_branch=[],
                    ),
                ],
            ),
            Return(lineno=7),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        final_cond = next(r for r in routers if r.condition is not None and r.condition.test == 'p["final"]')
        assert "end_flow" in final_cond.true_branch_actors

    def test_while_inside_if(self):
        ops = [
            Condition(
                lineno=2,
                test='p["should_loop"]',
                true_branch=[
                    WhileLoop(
                        lineno=3,
                        test='p["i"] < 10',
                        body=[ActorCall(lineno=4, name="handler")],
                    ),
                ],
                false_branch=[ActorCall(lineno=6, name="handler_b")],
            ),
            Return(lineno=7),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        while_conds = [r for r in routers if r.condition is not None and "while" in r.name]
        assert len(while_conds) == 1

    def test_while_empty_body_produces_loop_back(self):
        ops = [
            WhileLoop(
                lineno=3,
                test='p["i"] < 10',
                body=[],
            ),
            Return(lineno=5),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        loop_backs = [r for r in routers if r.is_loop_back]
        assert len(loop_backs) == 1

    def test_sequential_while_loops(self):
        ops = [
            WhileLoop(
                lineno=3,
                test='p["i"] < 10',
                body=[ActorCall(lineno=4, name="handler_a")],
            ),
            WhileLoop(
                lineno=6,
                test='p["j"] < 5',
                body=[ActorCall(lineno=7, name="handler_b")],
            ),
            Return(lineno=8),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        while_conds = [r for r in routers if r.condition is not None and "while" in r.name]
        assert len(while_conds) == 2

        # Find first and second while by their condition test
        first_while = next(r for r in while_conds if r.condition is not None and 'p["i"]' in r.condition.test)
        second_while = next(r for r in while_conds if r.condition is not None and 'p["j"]' in r.condition.test)

        # First while's exit (false branch) should lead to second while
        assert second_while.name in first_while.false_branch_actors

    def test_while_with_break_and_continue_combined(self):
        ops = [
            WhileLoop(
                lineno=3,
                test='p["i"] < 10',
                body=[
                    Mutation(lineno=4, code='p["i"] += 1'),
                    Condition(
                        lineno=5,
                        test='p["skip"]',
                        true_branch=[Continue(lineno=6)],
                        false_branch=[],
                    ),
                    ActorCall(lineno=7, name="handler"),
                    Condition(
                        lineno=8,
                        test='p["stop"]',
                        true_branch=[Break(lineno=9)],
                        false_branch=[],
                    ),
                ],
            ),
            ActorCall(lineno=10, name="finalize"),
            Return(lineno=11),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        loop_back = next(r for r in routers if r.is_loop_back)

        skip_cond = next(r for r in routers if r.condition is not None and r.condition.test == 'p["skip"]')
        assert loop_back.name in skip_cond.true_branch_actors

        stop_cond = next(r for r in routers if r.condition is not None and r.condition.test == 'p["stop"]')
        assert "finalize" in stop_cond.true_branch_actors
