import { useState, useEffect } from "react";
import { createRoot } from "react-dom/client";
import { FlowDiagram } from "./components/FlowDiagram";
import type { FlowGraph } from "./types";
import "./tokens/theme.css";

function App() {
  const [graph, setGraph] = useState<FlowGraph | null>(null);
  const [flows, setFlows] = useState<string[]>([]);
  const [selected, setSelected] = useState<string>("");

  useEffect(() => {
    fetch("/api/flows")
      .then((r) => r.json())
      .then(setFlows);
  }, []);

  useEffect(() => {
    if (selected) {
      fetch(`/api/flows/${selected}/graph`)
        .then((r) => r.json())
        .then(setGraph);
    }
  }, [selected]);

  return (
    <div style={{ height: "100vh", display: "flex", flexDirection: "column" }}>
      <header
        style={{ padding: 8, borderBottom: "1px solid var(--asya-border)" }}
      >
        <select
          value={selected}
          onChange={(e) => setSelected(e.target.value)}
          aria-label="Select flow"
        >
          <option value="">Select a flow...</option>
          {flows.map((f) => (
            <option key={f} value={f}>
              {f}
            </option>
          ))}
        </select>
      </header>
      <main style={{ flex: 1 }}>
        {graph && <FlowDiagram graph={graph} />}
      </main>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
