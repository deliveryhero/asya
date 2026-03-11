"""IPython magic commands for Asya."""

from __future__ import annotations

import shlex


try:
    from IPython.core.magic import Magics, line_magic, magics_class
except ImportError as e:
    raise ImportError("Install asya-lab[jupyter] for Jupyter support") from e


@magics_class
class AsyaMagics(Magics):
    @line_magic
    def asya(self, line: str):
        """Asya magic: %asya compile <flow>"""
        args = shlex.split(line)
        if not args:
            print("Usage: %asya compile <flow_name>")
            return

        if args[0] == "compile" and len(args) >= 2:
            flow_name = args[1]
            return self._compile_flow(flow_name)

        print(f"Unknown command: {args[0]}")
        return None

    def _compile_flow(self, flow_name: str):
        from pathlib import Path

        from asya_lab.flow.compiler import FlowCompiler
        from asya_lab.jupyter.widget import FlowWidget

        candidates = list(Path.cwd().rglob(f"**/{flow_name}.py"))
        if not candidates:
            print(f"[-] Flow source '{flow_name}.py' not found")
            return None

        compiler = FlowCompiler()
        source = candidates[0].read_text()
        compiler.compile(source, str(candidates[0]))
        graph = compiler.generate_graph()

        widget = FlowWidget(graph=graph)
        from IPython.display import display

        display(widget)
        return widget


def load_ipython_extension(ipython):
    ipython.register_magics(AsyaMagics)
