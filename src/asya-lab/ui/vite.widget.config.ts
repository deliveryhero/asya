import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    lib: {
      entry: "src/widgets/flow_widget.tsx",
      formats: ["es"],
      fileName: "flow_widget",
    },
    outDir: "../asya_lab/static",
    emptyOutDir: false,
  },
});
