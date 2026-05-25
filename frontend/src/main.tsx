import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";

// Standard Vite + React entry point. StrictMode double-invokes effects
// in dev to surface subtle bugs early — has no effect in production builds.
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
