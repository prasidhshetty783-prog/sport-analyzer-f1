import React from "react";
import ReactDOM from "react-dom/client";

// Type faces are loaded via <link> in index.html (Archivo + JetBrains Mono,
// Google Fonts) — no font npm dependency bundled.
import App from "./App";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
