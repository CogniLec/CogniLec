import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { isRecordingActive, onceRecordingStops } from "./services/recordingActivity";
import "./index.css";

// Without this, an already-open tab keeps running its old, precached JS
// bundle (build-time-baked apiBaseUrl included) even after a new service
// worker activates in the background -- confirmed live: this caused
// "fetch error on login" until the user manually cleared cookies, which
// only incidentally worked because it also wipes Cache Storage/SW state
// (see vite.config.ts's skipWaiting/clientsClaim comment). This listener
// reloads the tab exactly once when a new SW actually takes control, so
// stale-bundle fetch failures fix themselves instead of needing that.
//
// If a recording is in progress when this fires, the reload is deferred
// until recording stops -- an unconditional reload here would silently
// wipe the in-progress capture with no warning (docs/gaps.md #33j).
if ("serviceWorker" in navigator) {
  let reloaded = false;
  const doReload = (): void => {
    if (reloaded) return;
    reloaded = true;
    window.location.reload();
  };
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (isRecordingActive()) {
      onceRecordingStops(doReload);
    } else {
      doReload();
    }
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
