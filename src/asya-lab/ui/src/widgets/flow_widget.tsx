import { createRoot } from "react-dom/client";
import { FlowDiagram } from "../components/FlowDiagram";
import { AnywidgetAsyaProvider } from "../providers/AnywidgetAsyaProvider";
import type { FlowGraph } from "../types";

interface AnywidgetModel {
  get(key: string): unknown;
  set(key: string, value: unknown): void;
  on(event: string, callback: () => void): void;
  off(event: string, callback: () => void): void;
  save_changes(): void;
}

export function render({
  model,
  el,
}: {
  model: AnywidgetModel;
  el: HTMLElement;
}) {
  const container = document.createElement("div");
  container.style.width = "100%";
  container.style.height = "500px";
  el.appendChild(container);

  const root = createRoot(container);

  function update() {
    const graph = model.get("graph") as FlowGraph;
    if (graph && graph.nodes) {
      root.render(
        <AnywidgetAsyaProvider model={model}>
          <FlowDiagram graph={graph} />
        </AnywidgetAsyaProvider>,
      );
    }
  }

  update();
  model.on("change:graph", update);

  return () => {
    model.off("change:graph", update);
    root.unmount();
  };
}
