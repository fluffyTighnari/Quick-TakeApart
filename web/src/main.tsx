import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";
import { initUiPreferences } from "./core/prefs";
import "./styles/tokens.css";
import "./styles/layout.css";
import "./styles/components.css";

initUiPreferences();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
