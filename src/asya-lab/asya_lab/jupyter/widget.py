"""Anywidget-based FlowWidget for Jupyter notebooks."""

from __future__ import annotations

import pathlib


try:
    import anywidget
    import traitlets
except ImportError as e:
    raise ImportError("Install asya-lab[jupyter] for Jupyter support") from e


class FlowWidget(anywidget.AnyWidget):
    _esm = pathlib.Path(__file__).parent.parent / "static" / "flow_widget.js"

    graph = traitlets.Dict({}).tag(sync=True)
    actors = traitlets.List([]).tag(sync=True)
    status = traitlets.Dict({}).tag(sync=True)
    selected_node = traitlets.Unicode("").tag(sync=True)
