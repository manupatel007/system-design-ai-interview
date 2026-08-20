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
  buildStructuredAiProposal,
  removeAiProposal,
} from "./ai-preview.js";
import {
  buildCanvasFeedbackOverlays,
  removeCanvasFeedback,
} from "./canvas-feedback.js";
import "./ai-preview.css";
import { buildDelta, normalizeScene, sceneFingerprint } from "./diagram.js";

window.EXCALIDRAW_ASSET_PATH = "/static/excalidraw/assets/";

function DiagramEditor() {
  const api = useRef(null);
  const timer = useRef(null);
  const revision = useRef(0);
  const previous = useRef(null);
  const previousFingerprint = useRef("");
  const feedbackTimer = useRef(null);
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

  const clearCanvasFeedback = useCallback(() => {
    const instance = api.current;
    window.clearTimeout(feedbackTimer.current);
    if (!instance) return;
    const currentElements = [...instance.getSceneElements()];
    const nextElements = removeCanvasFeedback(currentElements);
    if (nextElements.length === currentElements.length) return;
    instance.updateScene({
      elements: nextElements,
      captureUpdate: CaptureUpdateAction.NEVER,
    });
  }, []);

  const showCanvasFeedback = useCallback(
    (detail = {}) => {
      const instance = api.current;
      if (!instance) return;
      window.clearTimeout(feedbackTimer.current);
      const currentElements = [...instance.getSceneElements()];
      const baseElements = removeCanvasFeedback(currentElements);
      const references = Array.isArray(detail.references) ? detail.references : [];
      const feedbackId = String(detail.feedbackId ?? `feedback-${Date.now()}`);
      const overlay = buildCanvasFeedbackOverlays(
        baseElements,
        references,
        feedbackId,
      );
      if (!overlay.skeletons.length) {
        if (baseElements.length !== currentElements.length) {
          instance.updateScene({
            elements: baseElements,
            captureUpdate: CaptureUpdateAction.NEVER,
          });
        }
        return;
      }
      const converted = convertToExcalidrawElements(overlay.skeletons, {
        regenerateIds: false,
      }).map((element) => ({
        ...element,
        locked: true,
        customData: {
          ...element.customData,
          author: "ai",
          aiPreview: true,
          aiCanvasFeedback: true,
          aiFeedbackId: feedbackId,
        },
      }));
      instance.updateScene({
        elements: [...baseElements, ...converted],
        captureUpdate: CaptureUpdateAction.NEVER,
      });
      if (detail.focus) {
        const targetIds = new Set(overlay.targetIds);
        const targets = baseElements.filter((element) => targetIds.has(element.id));
        if (targets.length) {
          instance.scrollToContent(targets, {
            fitToViewport: true,
            viewportZoomFactor: 0.55,
            minZoom: 0.5,
            maxZoom: 1.25,
            animate: true,
            duration: 450,
          });
        }
      }
      const requestedDuration = Number(detail.durationMs) || 18_000;
      const duration = Math.min(30_000, Math.max(5_000, requestedDuration));
      feedbackTimer.current = window.setTimeout(clearCanvasFeedback, duration);
    },
    [clearCanvasFeedback],
  );

  useEffect(() => {
    const clear = () => {
      window.clearTimeout(feedbackTimer.current);
      api.current?.updateScene({ elements: [] });
      setActiveProposal(null);
      setAcceptedProposalIds([]);
    };
    window.addEventListener("diagram.clear", clear);
    return () => {
      window.removeEventListener("diagram.clear", clear);
      window.clearTimeout(timer.current);
      window.clearTimeout(feedbackTimer.current);
    };
  }, []);

  useEffect(() => {
    const show = ({ detail }) => showCanvasFeedback(detail);
    const clear = () => clearCanvasFeedback();
    window.addEventListener("diagram.feedback.show", show);
    window.addEventListener("diagram.feedback.clear", clear);
    return () => {
      window.removeEventListener("diagram.feedback.show", show);
      window.removeEventListener("diagram.feedback.clear", clear);
    };
  }, [clearCanvasFeedback, showCanvasFeedback]);

  const showModelProposal = useCallback(
    (detail = {}) => {
      const instance = api.current;
      if (!instance) return;
      const currentElements = activeProposal
        ? removeAiProposal(
            instance.getSceneElements(),
            activeProposal.proposalId,
          )
        : [...instance.getSceneElements()];
      const appState = instance.getAppState();
      const zoom = appState.zoom?.value ?? 1;
      const viewport = {
        centerX: appState.width / (2 * zoom) - appState.scrollX,
        centerY: appState.height / (2 * zoom) - appState.scrollY,
      };
      const proposalId = String(
        detail.proposalId ??
          globalThis.crypto?.randomUUID?.() ??
          "proposal-" + Date.now(),
      );
      const proposal = buildStructuredAiProposal(
        currentElements,
        detail.proposal,
        detail.anchorObjectIds,
        viewport,
        proposalId,
      );
      if (!proposal.skeletons.length) return;
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
      window.requestAnimationFrame(() => {
        const proposalElements = instance
          .getSceneElements()
          .filter(
            (element) => element.customData?.aiProposalId === proposalId,
          );
        if (!proposalElements.length) return;
        instance.scrollToContent(proposalElements, {
          fitToViewport: true,
          viewportZoomFactor:
            proposal.kind === "reference_architecture" ? 0.72 : 0.55,
          minZoom: 0.2,
          maxZoom: 1.15,
          animate: true,
          duration: 550,
        });
      });
    },
    [activeProposal],
  );

  useEffect(() => {
    const show = ({ detail }) => showModelProposal(detail);
    window.addEventListener("diagram.proposal.show", show);
    return () => window.removeEventListener("diagram.proposal.show", show);
  }, [showModelProposal]);

  const acceptSuggestion = useCallback(() => {
    const instance = api.current;
    if (!instance || !activeProposal) return;
    const nextElements = acceptAiProposal(
      instance.getSceneElements(),
      activeProposal.proposalId,
    );
    instance.updateScene({
      elements: nextElements,
      captureUpdate: CaptureUpdateAction.NEVER,
    });
    publish(nextElements, instance.getAppState());
    setAcceptedProposalIds((identifiers) => [
      ...identifiers,
      activeProposal.proposalId,
    ]);
    setActiveProposal(null);
  }, [activeProposal, publish]);

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
    const nextElements = removeAiProposal(
      instance.getSceneElements(),
      proposalId,
    );
    instance.updateScene({
      elements: nextElements,
      captureUpdate: CaptureUpdateAction.NEVER,
    });
    publish(nextElements, instance.getAppState());
    setAcceptedProposalIds((identifiers) => identifiers.slice(0, -1));
  }, [acceptedProposalIds, publish]);

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
        <span>✦ AI canvas</span>
        <span className="ai-preview-badge">
          {proposal ? "Model proposal" : "Voice controlled"}
        </span>
      </div>
      <p className="ai-preview-copy" aria-live="polite">
        {proposal
          ? proposal.title + ": " + proposal.description
          : "Ask what to draw, or request a complete reference architecture."}
      </p>
      <div className="ai-preview-actions">
        {proposal ? (
          <>
            <button className="ai-preview-button" type="button" onClick={onAccept}>
              {proposal.kind === "reference_architecture"
                ? "Keep reference"
                : "Keep suggestion"}
            </button>
            <button
              className="ai-preview-button secondary"
              type="button"
              onClick={onReject}
            >
              Reject
            </button>
          </>
        ) : null}
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
        Select objects before asking for scoped help. Kept AI references remain editable
        but excluded from candidate evidence.
      </small>
    </section>
  );
}

const root = document.querySelector("#excalidraw-root");
if (!root) throw new Error("Missing #excalidraw-root mount point");
createRoot(root).render(<DiagramEditor />);
