import {
  CaptureUpdateAction,
  convertToExcalidrawElements,
  Excalidraw,
} from "@excalidraw/excalidraw";
import "@excalidraw/excalidraw/index.css";
import React, { useCallback, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";

import {
  acceptAiProposal,
  buildAiTutorProposal,
  removeAiProposal,
} from "./ai-preview.js";
import "./ai-preview.css";
import { buildDelta, normalizeScene, sceneFingerprint } from "./diagram.js";

window.EXCALIDRAW_ASSET_PATH = "/static/excalidraw/assets/";

function DiagramEditor() {
  const api = useRef(null);
  const timer = useRef(null);
  const revision = useRef(0);
  const previous = useRef(null);
  const previousFingerprint = useRef("");
  const [activeProposal, setActiveProposal] = useState(null);
  const [acceptedProposalIds, setAcceptedProposalIds] = useState([]);

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
    const clear = () => {
      api.current?.updateScene({ elements: [] });
      setActiveProposal(null);
      setAcceptedProposalIds([]);
    };
    window.addEventListener("diagram.clear", clear);
    return () => {
      window.removeEventListener("diagram.clear", clear);
      window.clearTimeout(timer.current);
    };
  }, []);

  const previewSuggestion = useCallback(() => {
    const instance = api.current;
    if (!instance) return;
    const currentElements = activeProposal
      ? removeAiProposal(instance.getSceneElements(), activeProposal.proposalId)
      : [...instance.getSceneElements()];
    const appState = instance.getAppState();
    const zoom = appState.zoom?.value ?? 1;
    const viewport = {
      centerX: appState.width / (2 * zoom) - appState.scrollX,
      centerY: appState.height / (2 * zoom) - appState.scrollY,
    };
    const proposalId = globalThis.crypto?.randomUUID?.() ?? `preview-${Date.now()}`;
    const proposal = buildAiTutorProposal(
      currentElements,
      appState.selectedElementIds,
      viewport,
      proposalId,
    );
    const converted = convertToExcalidrawElements(proposal.skeletons, {
      regenerateIds: false,
    }).map((element) => ({
      ...element,
      locked: true,
      customData: {
        ...element.customData,
        author: "ai",
        aiPreview: true,
        aiProposalId: proposalId,
        aiPreviewStatus: "proposed",
      },
    }));
    instance.updateScene({
      elements: [...currentElements, ...converted],
      captureUpdate: CaptureUpdateAction.NEVER,
    });
    setActiveProposal(proposal);
  }, [activeProposal]);

  const acceptSuggestion = useCallback(() => {
    const instance = api.current;
    if (!instance || !activeProposal) return;
    instance.updateScene({
      elements: acceptAiProposal(
        instance.getSceneElements(),
        activeProposal.proposalId,
      ),
      captureUpdate: CaptureUpdateAction.NEVER,
    });
    setAcceptedProposalIds((identifiers) => [
      ...identifiers,
      activeProposal.proposalId,
    ]);
    setActiveProposal(null);
  }, [activeProposal]);

  const rejectSuggestion = useCallback(() => {
    const instance = api.current;
    if (!instance || !activeProposal) return;
    instance.updateScene({
      elements: removeAiProposal(
        instance.getSceneElements(),
        activeProposal.proposalId,
      ),
      captureUpdate: CaptureUpdateAction.NEVER,
    });
    setActiveProposal(null);
  }, [activeProposal]);

  const undoAcceptedSuggestion = useCallback(() => {
    const instance = api.current;
    const proposalId = acceptedProposalIds.at(-1);
    if (!instance || !proposalId) return;
    instance.updateScene({
      elements: removeAiProposal(instance.getSceneElements(), proposalId),
      captureUpdate: CaptureUpdateAction.NEVER,
    });
    setAcceptedProposalIds((identifiers) => identifiers.slice(0, -1));
  }, [acceptedProposalIds]);

  return (
    <Excalidraw
      excalidrawAPI={(instance) => {
        api.current = instance;
      }}
      langCode="en"
      name="System Design Interview"
      onChange={publish}
      renderTopRightUI={(isMobile) => (
        <AiPreviewPanel
          compact={isMobile}
          proposal={activeProposal}
          acceptedCount={acceptedProposalIds.length}
          onPreview={previewSuggestion}
          onAccept={acceptSuggestion}
          onReject={rejectSuggestion}
          onUndo={undoAcceptedSuggestion}
        />
      )}
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

function AiPreviewPanel({
  compact,
  proposal,
  acceptedCount,
  onPreview,
  onAccept,
  onReject,
  onUndo,
}) {
  return (
    <section
      className={`ai-preview-panel${compact ? " compact" : ""}`}
      aria-label="AI canvas preview"
      onPointerDown={(event) => event.stopPropagation()}
    >
      <div className="ai-preview-heading">
        <span>✦ AI tutor</span>
        <span className="ai-preview-badge">Simulated preview</span>
      </div>
      <p className="ai-preview-copy" aria-live="polite">
        {proposal?.description ??
          "See how an AI-owned suggestion could appear over your diagram."}
      </p>
      <div className="ai-preview-actions">
        {proposal ? (
          <>
            <button className="ai-preview-button" type="button" onClick={onAccept}>
              Accept
            </button>
            <button
              className="ai-preview-button secondary"
              type="button"
              onClick={onReject}
            >
              Reject
            </button>
          </>
        ) : (
          <button className="ai-preview-button" type="button" onClick={onPreview}>
            Preview suggestion
          </button>
        )}
        {!proposal && acceptedCount > 0 ? (
          <button
            className="ai-preview-button secondary"
            type="button"
            onClick={onUndo}
          >
            Undo AI
          </button>
        ) : null}
      </div>
      <small className="ai-preview-hint">
        Select a component first for a contextual placement. Preview objects are excluded
        from interview evidence.
      </small>
    </section>
  );
}

const root = document.querySelector("#excalidraw-root");
if (!root) throw new Error("Missing #excalidraw-root mount point");
createRoot(root).render(<DiagramEditor />);
