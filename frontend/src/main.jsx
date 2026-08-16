import { Excalidraw } from "@excalidraw/excalidraw";
import "@excalidraw/excalidraw/index.css";
import React, { useCallback, useEffect, useRef } from "react";
import { createRoot } from "react-dom/client";

import { buildDelta, normalizeScene, sceneFingerprint } from "./diagram.js";

window.EXCALIDRAW_ASSET_PATH = "/static/excalidraw/assets/";

function DiagramEditor() {
  const api = useRef(null);
  const timer = useRef(null);
  const revision = useRef(0);
  const previous = useRef(null);
  const previousFingerprint = useRef("");

  const publish = useCallback((elements, appState) => {
    const normalized = normalizeScene(elements, appState);
    const fingerprint = sceneFingerprint(normalized);
    if (fingerprint === previousFingerprint.current) return;
    previousFingerprint.current = fingerprint;
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      revision.current += 1;
      const snapshot = {
        ...normalized,
        revision: revision.current,
        delta: buildDelta(previous.current, normalized),
      };
      previous.current = snapshot;
      window.__diagramSnapshot = snapshot;
      window.dispatchEvent(new CustomEvent("diagram.snapshot", { detail: snapshot }));
    }, 350);
  }, []);

  useEffect(() => {
    const clear = () => api.current?.updateScene({ elements: [] });
    window.addEventListener("diagram.clear", clear);
    return () => {
      window.removeEventListener("diagram.clear", clear);
      window.clearTimeout(timer.current);
    };
  }, []);

  return (
    <Excalidraw
      excalidrawAPI={(instance) => {
        api.current = instance;
      }}
      langCode="en"
      name="System Design Interview"
      onChange={publish}
      theme="dark"
      UIOptions={{
        canvasActions: {
          changeViewBackgroundColor: true,
          export: { saveFileToDisk: true },
          loadScene: true,
          saveToActiveFile: false,
        },
      }}
    />
  );
}

const root = document.querySelector("#excalidraw-root");
if (!root) throw new Error("Missing #excalidraw-root mount point");
createRoot(root).render(<DiagramEditor />);
