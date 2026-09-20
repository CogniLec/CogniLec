import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";
import { ErrorBoundary } from "./components/ErrorBoundary";
import "./index.css";

// Without this, an already-open tab keeps running its old, precached JS
// bundle (build-time-baked apiBaseUrl included) even after a new service
// worker activates in the background -- confirmed live: this caused
// "fetch error on login" until the user manually cleared cookies, which
// only incidentally worked because it also wipes Cache Storage/SW state
// (see vite.config.ts's skipWaiting/clientsClaim comment). This listener
// reloads the tab exactly once when a new SW actually takes control, so
// stale-bundle fetch failures fix themselves instead of needing that.
if ("serviceWorker" in navigator) {
  let reloaded = false;
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (reloaded) return;
    reloaded = true;
    window.location.reload();
  });
}

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("Root element #root not found");
}

ReactDOM.createRoot(rootElement).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>,
);
