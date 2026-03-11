"""Tests for Jupyter widget."""

import pytest


class TestFlowWidget:
    def test_import(self):
        pytest.importorskip("anywidget")
        from asya_lab.jupyter.widget import FlowWidget

        w = FlowWidget(graph={"flow": "test", "nodes": [], "edges": [], "groups": []})
        assert w.graph["flow"] == "test"

    def test_traitlets_sync(self):
        pytest.importorskip("anywidget")
        from asya_lab.jupyter.widget import FlowWidget

        w = FlowWidget()
        w.graph = {"flow": "updated", "nodes": [], "edges": [], "groups": []}
        assert w.graph["flow"] == "updated"
