const elements = {
  status: document.querySelector("#status"),
  setup: document.querySelector("#setup"),
  connect: document.querySelector("#connect"),
  microphone: document.querySelector("#microphone"),
  finish: document.querySelector("#finish"),
  disconnect: document.querySelector("#disconnect"),
  problem: document.querySelector("#problem"),
  glossary: document.querySelector("#glossary"),
  assistancePolicy: document.querySelector("#assistance-policy"),
  candidateCard: document.querySelector("#candidate-card"),
  interviewerCard: document.querySelector("#interviewer-card"),
  candidateState: document.querySelector("#candidate-state"),
  interviewerState: document.querySelector("#interviewer-state"),
  candidate: document.querySelector("#candidate"),
  interviewer: document.querySelector("#interviewer"),
  interviewPhase: document.querySelector("#interview-phase"),
  currentQuestion: document.querySelector("#current-question"),
  transcriptScroll: document.querySelector("#transcript-scroll"),
  transcriptFeed: document.querySelector("#transcript-feed"),
  transcriptEmpty: document.querySelector("#transcript-empty"),
  liveIndicator: document.querySelector(".live-indicator"),
  feedback: document.querySelector("#interview-feedback"),
  feedbackSummary: document.querySelector("#feedback-summary"),
  feedbackStrengths: document.querySelector("#feedback-strengths"),
  feedbackImprovements: document.querySelector("#feedback-improvements"),
  feedbackNotDiscussed: document.querySelector("#feedback-not-discussed"),
  diagramSummary: document.querySelector("#diagram-summary"),
  clear: document.querySelector("#clear"),
  walkThrough: document.querySelector("#walk-through"),
  guidedTakeover: document.querySelector("#guided-takeover"),
  guidedProgress: document.querySelector("#guided-progress"),
  guidedTitle: document.querySelector("#guided-title"),
  guidedObjective: document.querySelector("#guided-objective"),
  guidedScope: document.querySelector("#guided-scope"),
  guidedQuestions: document.querySelector("#guided-questions"),
  guidedContinue: document.querySelector("#guided-continue"),
  guidedWhy: document.querySelector("#guided-why"),
  guidedAlternative: document.querySelector("#guided-alternative"),
  guidedTakeBack: document.querySelector("#guided-take-back"),
};

let socket;
let mediaStream;
let audioContext;
let captureNode;
let captureWorkletLoaded = false;
let microphoneActive = false;
let interviewCompleted = false;
const playbackSources = new Set();
let playbackCursor = 0;
let latestDiagramSnapshot = window.__diagramSnapshot ?? null;
let pendingCanvasReferences = [];
let pendingAssistance = null;
let assistantResponseActive = false;
let latestGuidedTakeover = null;
let pendingGuidedCanvasRevision = null;

function setStatus(text, connected = false) {
  elements.status.textContent = text;
  elements.status.classList.toggle("connected", connected);
  elements.liveIndicator.classList.toggle("active", connected);
}

function setParticipantState(element, text, tone = "") {
  element.textContent = text;
  if (tone) element.dataset.tone = tone;
  else delete element.dataset.tone;
}

function setCardActive(element, active) {
  element.classList.toggle("is-active", active);
}

function setSetupDisabled(disabled) {
  elements.problem.disabled = disabled;
  elements.glossary.disabled = disabled;
  elements.assistancePolicy.disabled = disabled;
  if (disabled) elements.setup.open = false;
}

function send(type, payload = {}) {
  if (socket?.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ type, payload }));
  }
}

function setGuidedControlsDisabled() {
  const connected = socket?.readyState === WebSocket.OPEN;
  const guidedActive = Boolean(latestGuidedTakeover?.active);
  const disabled = !connected || assistantResponseActive || interviewCompleted;
  elements.walkThrough.disabled = disabled || guidedActive;
  elements.guidedContinue.disabled =
    disabled || !guidedActive || pendingGuidedCanvasRevision !== null;
  elements.guidedContinue.title = pendingGuidedCanvasRevision !== null
    ? "Waiting for the guided canvas step to sync"
    : "";
  for (const control of [
    elements.guidedWhy,
    elements.guidedAlternative,
    elements.guidedTakeBack,
  ]) {
    control.disabled = disabled || !guidedActive;
  }
  elements.guidedQuestions
    .querySelectorAll("button")
    .forEach((button) => { button.disabled = disabled || !guidedActive; });
}

function sendGuidedCommand(command, question = "") {
  if (assistantResponseActive || interviewCompleted) return;
  assistantResponseActive = true;
  setGuidedControlsDisabled();
  send("guided.takeover.command", { command, question });
}

function resetTranscript() {
  elements.transcriptFeed.querySelectorAll(".transcript-entry").forEach((entry) => entry.remove());
  elements.transcriptEmpty.hidden = false;
  elements.feedback.hidden = true;
  pendingCanvasReferences = [];
  pendingAssistance = null;
  clearCanvasFeedback();
}

function appendTranscript(speaker, text, references = [], assistance = null) {
  const normalizedText = String(text ?? "").trim();
  if (!normalizedText) return;

  elements.transcriptEmpty.hidden = true;
  const entry = document.createElement("article");
  entry.className = `transcript-entry ${speaker}`;

  const header = document.createElement("header");
  const name = document.createElement("span");
  name.className = "transcript-speaker";
  name.textContent = speaker === "candidate" ? "You" : "AI interviewer";
  const time = document.createElement("time");
  time.className = "transcript-time";
  time.dateTime = new Date().toISOString();
  time.textContent = new Intl.DateTimeFormat([], {
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date());
  header.append(name, time);

  const message = document.createElement("p");
  message.textContent = normalizedText;
  entry.append(header, message);
  if (speaker === "interviewer" && assistance) {
    const badge = document.createElement("span");
    badge.className = "transcript-assistance";
    badge.dataset.level = assistance.level;
    badge.textContent = assistance.label + " " + assistance.requestIndex;
    badge.title = assistance.policy + " support for " + assistance.topic;
    entry.append(badge);
  }
  if (speaker === "interviewer" && references.length) {
    const referenceList = document.createElement("div");
    referenceList.className = "transcript-references";
    referenceList.setAttribute("aria-label", "Referenced diagram areas");
    for (const reference of references) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "transcript-reference";
      button.textContent = `[${reference.displayIndex}] ${reference.label}`;
      button.addEventListener("click", () => {
        showCanvasFeedback(
          [reference],
          `transcript-${crypto.randomUUID()}`,
          { focus: true, durationMs: 14_000 },
        );
      });
      referenceList.append(button);
    }
    entry.append(referenceList);
  }
  elements.transcriptFeed.append(entry);

  const entries = elements.transcriptFeed.querySelectorAll(".transcript-entry");
  if (entries.length > 100) entries[0].remove();
  requestAnimationFrame(() => {
    elements.transcriptScroll.scrollTop = elements.transcriptScroll.scrollHeight;
  });
}

function normalizeAssistance(payload) {
  const labels = {
    nudge: "Hint",
    concept: "Concept",
    example: "Worked example",
    reference: "Reference architecture",
  };
  const level = String(payload?.level ?? "");
  if (!labels[level]) return null;
  return {
    level,
    label: labels[level],
    policy: String(payload.policy ?? "adaptive"),
    requestIndex: Math.max(1, Number(payload.requestIndex) || 1),
    topic: String(payload.topic ?? "current question"),
  };
}

function normalizeCanvasReferences(references) {
  if (!Array.isArray(references)) return [];
  return references.slice(0, 3).flatMap((reference, index) => {
    const label = String(reference?.label ?? "").trim();
    const objectIds = Array.isArray(reference?.objectIds)
      ? reference.objectIds.filter((identifier) => typeof identifier === "string")
      : [];
    if (!label || !objectIds.length) return [];
    return [{
      kind: String(reference.kind ?? "issue"),
      label,
      objectIds,
      displayIndex: index + 1,
    }];
  });
}

function showCanvasFeedback(
  references,
  feedbackId,
  { focus = true, durationMs = 18_000 } = {},
) {
  window.dispatchEvent(new CustomEvent("diagram.feedback.show", {
    detail: { references, feedbackId, focus, durationMs },
  }));
}

function clearCanvasFeedback() {
  window.dispatchEvent(new Event("diagram.feedback.clear"));
}

function showCanvasProposal(
  proposal,
  anchorObjectIds,
  proposalId,
  { autoAccept = false, guidedStep = null } = {},
) {
  window.dispatchEvent(new CustomEvent("diagram.proposal.show", {
    detail: { proposal, anchorObjectIds, proposalId, autoAccept, guidedStep },
  }));
}

function connect() {
  if (socket?.readyState === WebSocket.OPEN || socket?.readyState === WebSocket.CONNECTING) return;

  const scheme = location.protocol === "https:" ? "wss" : "ws";
  const sessionId = crypto.randomUUID();
  ensureAudioContext().resume().catch(() => {});
  socket = new WebSocket(`${scheme}://${location.host}/ws/interview/${sessionId}`);
  socket.binaryType = "arraybuffer";
  elements.connect.disabled = true;
  setStatus("Connecting...");
  setParticipantState(elements.interviewerState, "Joining", "busy");
  setCardActive(elements.interviewerCard, true);

  socket.addEventListener("open", () => {
    resetTranscript();
    setStatus("Connected", true);
    setSetupDisabled(true);
    elements.microphone.disabled = false;
    interviewCompleted = false;
    elements.finish.disabled = false;
    elements.finish.textContent = "Finish interview";
    elements.disconnect.disabled = false;
    assistantResponseActive = true;
    setGuidedControlsDisabled();
    elements.candidate.textContent = "Microphone is off.";
    elements.interviewer.textContent = "Preparing the first question...";
    setParticipantState(elements.candidateState, "Mic off", "muted");
    setParticipantState(elements.interviewerState, "Preparing", "busy");
    send("session.configure", {
      problem: elements.problem.value,
      glossary: elements.glossary.value.split(",").map((term) => term.trim()).filter(Boolean),
      assistancePolicy: elements.assistancePolicy.value,
    });
    if (latestDiagramSnapshot) send("canvas.snapshot", latestDiagramSnapshot);
  });

  socket.addEventListener("message", ({ data }) => {
    if (typeof data !== "string") return;
    const event = JSON.parse(data);
    const payload = event.payload ?? {};

    if (event.type === "candidate.speech.started") {
      pendingCanvasReferences = [];
      pendingAssistance = null;
      clearCanvasFeedback();
      setParticipantState(elements.candidateState, "Speaking", "active");
      setCardActive(elements.candidateCard, true);
    }
    if (event.type === "candidate.speech.ended") {
      setParticipantState(elements.candidateState, "Transcribing", "busy");
    }
    if (event.type === "candidate.transcript.rejected") {
      elements.candidate.textContent = "I could not transcribe that clearly. Please try again.";
      setParticipantState(
        elements.candidateState,
        microphoneActive ? "Try again" : "Mic off",
        microphoneActive ? "busy" : "muted",
      );
      setCardActive(elements.candidateCard, false);
    }
    if (event.type === "candidate.transcript.final") {
      elements.candidate.textContent = payload.text;
      appendTranscript("candidate", payload.text);
      setParticipantState(
        elements.candidateState,
        microphoneActive ? "Mic on" : "Mic off",
        microphoneActive ? "active" : "muted",
      );
      setCardActive(elements.candidateCard, false);
    }
    if (event.type === "assistant.response.started") {
      assistantResponseActive = true;
      setGuidedControlsDisabled();
      pendingCanvasReferences = [];
      pendingAssistance = null;
      clearCanvasFeedback();
      setParticipantState(elements.interviewerState, "Thinking", "busy");
      setCardActive(elements.interviewerCard, true);
    }
    if (event.type === "assistant.assistance") {
      pendingAssistance = normalizeAssistance(payload);
      if (pendingAssistance) {
        setParticipantState(
          elements.interviewerState,
          pendingAssistance.label,
          "assist",
        );
      }
    }
    if (event.type === "assistant.canvas.proposal") {
      if (payload.autoAccept === true) {
        pendingGuidedCanvasRevision =
          Math.max(0, Number(latestDiagramSnapshot?.revision) || 0) + 1;
        setGuidedControlsDisabled();
      }
      showCanvasProposal(
        payload.proposal,
        payload.anchorObjectIds,
        "proposal-" + event.sequence,
        {
          autoAccept: payload.autoAccept === true,
          guidedStep: payload.guidedStep ?? null,
        },
      );
    }
    if (event.type === "canvas.synced" && pendingGuidedCanvasRevision !== null) {
      const syncedRevision = Number(payload.revision);
      if (Number.isFinite(syncedRevision) && syncedRevision >= pendingGuidedCanvasRevision) {
        pendingGuidedCanvasRevision = null;
        setGuidedControlsDisabled();
      }
    }
    if (event.type === "assistant.canvas.references") {
      pendingCanvasReferences = normalizeCanvasReferences(payload.references);
      showCanvasFeedback(pendingCanvasReferences, `feedback-${event.sequence}`, {
        focus: true,
        durationMs: 20_000,
      });
    }
    if (event.type === "assistant.text.final") {
      elements.interviewer.textContent = payload.text;
      appendTranscript(
        "interviewer",
        payload.text,
        pendingCanvasReferences,
        pendingAssistance,
      );
      pendingCanvasReferences = [];
      pendingAssistance = null;
    }
    if (event.type === "assistant.audio.chunk") {
      setParticipantState(elements.interviewerState, "Speaking", "active");
      playPcm(payload.audio, payload.sampleRate);
    }
    if (event.type === "assistant.response.completed") {
      assistantResponseActive = false;
      setGuidedControlsDisabled();
      setParticipantState(elements.interviewerState, "Listening", "active");
      setCardActive(elements.interviewerCard, false);
    }
    if (event.type === "assistant.interrupted") {
      assistantResponseActive = false;
      setGuidedControlsDisabled();
      stopPlayback();
      clearCanvasFeedback();
      setParticipantState(elements.interviewerState, "Listening", "active");
      setCardActive(elements.interviewerCard, false);
    }
    if (event.type === "interview.state") renderInterviewState(payload);
    if (event.type === "interview.feedback") renderFeedback(payload);
    if (event.type === "error") {
      assistantResponseActive = false;
      setGuidedControlsDisabled();
      stopPlayback();
      setStatus(`Error: ${payload.message ?? payload.code}`);
      setParticipantState(elements.interviewerState, "Error", "muted");
      setCardActive(elements.interviewerCard, false);
      if (socket?.readyState === WebSocket.OPEN && !interviewCompleted) {
        elements.finish.disabled = false;
      }
    }
  });

  socket.addEventListener("close", () => resetConnection("Not connected"));
  socket.addEventListener("error", () => setStatus("Connection error"));
}

async function toggleMicrophone() {
  if (microphoneActive) {
    await stopMicrophone();
    return;
  }
  mediaStream = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
  });
  audioContext = ensureAudioContext();
  await audioContext.resume();
  if (!captureWorkletLoaded) {
    await audioContext.audioWorklet.addModule("/static/pcm-worklet.js");
    captureWorkletLoaded = true;
  }
  const source = audioContext.createMediaStreamSource(mediaStream);
  captureNode = new AudioWorkletNode(audioContext, "pcm-capture");
  const silentOutput = audioContext.createGain();
  silentOutput.gain.value = 0;
  captureNode.port.onmessage = ({ data }) => {
    if (socket?.readyState === WebSocket.OPEN) socket.send(data);
  };
  source.connect(captureNode).connect(silentOutput).connect(audioContext.destination);
  microphoneActive = true;
  elements.microphone.textContent = "Mute microphone";
  elements.microphone.setAttribute("aria-pressed", "true");
  elements.candidate.textContent = "Listening for your answer...";
  setParticipantState(elements.candidateState, "Mic on", "active");
}

async function stopMicrophone({ flush = true } = {}) {
  if (!microphoneActive) return;
  if (flush) send("audio.flush");
  captureNode?.disconnect();
  mediaStream?.getTracks().forEach((track) => track.stop());
  captureNode = undefined;
  mediaStream = undefined;
  microphoneActive = false;
  elements.microphone.textContent = "Start microphone";
  elements.microphone.setAttribute("aria-pressed", "false");
  if (socket?.readyState === WebSocket.OPEN) {
    setParticipantState(elements.candidateState, "Mic off", "muted");
  }
  setCardActive(elements.candidateCard, false);
}

async function disconnect() {
  await stopMicrophone();
  socket?.close();
  await audioContext?.close();
  audioContext = undefined;
}

async function finishInterview() {
  if (microphoneActive) await stopMicrophone();
  stopPlayback();
  elements.microphone.disabled = true;
  elements.finish.disabled = true;
  elements.finish.textContent = "Preparing feedback...";
  setParticipantState(elements.interviewerState, "Preparing feedback", "busy");
  setCardActive(elements.interviewerCard, true);
  send("interview.finish");
}

function resetConnection(status) {
  void stopMicrophone({ flush: false });
  setStatus(status);
  setSetupDisabled(false);
  elements.connect.disabled = false;
  elements.microphone.disabled = true;
  elements.finish.disabled = true;
  elements.finish.textContent = "Finish interview";
  elements.disconnect.disabled = true;
  elements.candidate.textContent = "Join when you are ready to begin.";
  elements.interviewer.textContent = "Waiting for you to join.";
  assistantResponseActive = false;
  latestGuidedTakeover = null;
  pendingGuidedCanvasRevision = null;
  elements.guidedTakeover.hidden = true;
  elements.guidedQuestions.replaceChildren();
  setGuidedControlsDisabled();
  elements.interviewPhase.textContent = "Not started";
  elements.currentQuestion.textContent = "The current question will appear here.";
  setParticipantState(elements.candidateState, "Not connected");
  setParticipantState(elements.interviewerState, "Idle");
  setCardActive(elements.candidateCard, false);
  setCardActive(elements.interviewerCard, false);
  stopPlayback();
  pendingCanvasReferences = [];
  pendingAssistance = null;
  clearCanvasFeedback();
}

function ensureAudioContext() {
  if (!audioContext || audioContext.state === "closed") {
    audioContext = new AudioContext();
    captureWorkletLoaded = false;
  }
  return audioContext;
}

function playPcm(encodedAudio, sampleRate) {
  if (!encodedAudio) return;
  const bytes = Uint8Array.from(atob(encodedAudio), (character) => character.charCodeAt(0));
  const samples = new Int16Array(bytes.buffer);
  const context = ensureAudioContext();
  if (context.state === "suspended") context.resume().catch(() => {});
  const buffer = context.createBuffer(1, samples.length, sampleRate);
  const channel = buffer.getChannelData(0);
  for (let index = 0; index < samples.length; index += 1) channel[index] = samples[index] / 32768;
  const source = context.createBufferSource();
  source.buffer = buffer;
  source.connect(context.destination);
  playbackSources.add(source);
  source.addEventListener("ended", () => playbackSources.delete(source));
  const startAt = Math.max(context.currentTime + 0.01, playbackCursor);
  source.start(startAt);
  playbackCursor = startAt + buffer.duration;
}

function stopPlayback() {
  playbackSources.forEach((source) => {
    try { source.stop(); } catch (_) { /* already stopped */ }
  });
  playbackSources.clear();
  playbackCursor = 0;
}

function renderDiagram(snapshot) {
  const assistantNodes = snapshot.assistantLayer?.nodes?.length ?? 0;
  const assistantEdges = snapshot.assistantLayer?.edges?.length ?? 0;
  const assistant = assistantNodes || assistantEdges
    ? ` · AI reference: ${assistantNodes} components, ${assistantEdges} relationships`
    : "";
  const delta = snapshot.delta?.summary ? ` · ${snapshot.delta.summary}` : "";
  elements.diagramSummary.textContent =
    `${snapshot.nodes.length} candidate components · ${snapshot.edges.length} relationships${assistant}${delta}`;
}

function renderInterviewState(state) {
  interviewCompleted = Boolean(state.completed);
  renderGuidedTakeover(state.guidedTakeover);
  elements.interviewPhase.textContent = humanize(state.phase ?? "not_started");
  elements.currentQuestion.textContent =
    state.currentQuestion?.text ?? (state.completed ? "Interview complete." : "Listening...");
  if (state.feedback) renderFeedback(state.feedback);
  if (state.completed) {
    elements.finish.disabled = true;
    elements.finish.textContent = "Interview complete";
    elements.microphone.disabled = true;
    setParticipantState(elements.interviewerState, "Complete", "active");
    setCardActive(elements.interviewerCard, false);
  }
}

function renderGuidedTakeover(takeover) {
  latestGuidedTakeover = takeover && typeof takeover === "object" ? takeover : null;
  const active = Boolean(latestGuidedTakeover?.active);
  elements.guidedTakeover.hidden = !active;
  elements.guidedQuestions.replaceChildren();
  if (!active) {
    setGuidedControlsDisabled();
    return;
  }

  const step = latestGuidedTakeover.step ?? {};
  const currentStep = Number(latestGuidedTakeover.currentStep) || 1;
  const totalSteps = Number(latestGuidedTakeover.totalSteps) || 1;
  elements.guidedProgress.textContent = `Step ${currentStep} of ${totalSteps}`;
  elements.guidedTitle.textContent = step.title || "Architecture step";
  elements.guidedObjective.textContent = step.goal || latestGuidedTakeover.objective || "";
  elements.guidedScope.textContent = latestGuidedTakeover.objective || "";
  elements.guidedContinue.textContent =
    currentStep >= totalSteps && step.status === "completed"
      ? "Finish walkthrough"
      : "Continue";

  const questions = Array.isArray(latestGuidedTakeover.suggestedQuestions)
    ? latestGuidedTakeover.suggestedQuestions
    : [];
  for (const question of questions) {
    const text = String(question ?? "").trim();
    if (!text) continue;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "guided-question";
    button.textContent = text;
    button.addEventListener("click", () => sendGuidedCommand("question", text));
    elements.guidedQuestions.append(button);
  }
  setGuidedControlsDisabled();
}

function renderFeedback(feedback) {
  elements.feedback.hidden = false;
  elements.feedbackSummary.textContent = feedback.summary || "Interview complete.";
  renderList(elements.feedbackStrengths, feedback.strengths, "No demonstrated strengths yet.");
  renderList(
    elements.feedbackImprovements,
    feedback.improvements,
    "No specific improvements recorded.",
  );
  elements.feedbackNotDiscussed.textContent = feedback.notDiscussed?.length
    ? `Not discussed: ${feedback.notDiscussed.join(", ")}`
    : "All rubric areas received some evidence.";
  requestAnimationFrame(() => {
    elements.transcriptScroll.scrollTop = elements.transcriptScroll.scrollHeight;
  });
}

function renderList(element, items = [], emptyText) {
  element.replaceChildren();
  const values = items.length ? items : [emptyText];
  for (const value of values) {
    const item = document.createElement("li");
    item.textContent = value;
    element.append(item);
  }
}

function humanize(value) {
  return String(value).replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

window.addEventListener("diagram.snapshot", ({ detail }) => {
  latestDiagramSnapshot = detail;
  renderDiagram(detail);
  send("canvas.snapshot", detail);
});

elements.clear.addEventListener("click", () => {
  window.dispatchEvent(new Event("diagram.clear"));
});
elements.walkThrough.addEventListener("click", () => {
  if (assistantResponseActive || interviewCompleted) return;
  const selectedIds = latestDiagramSnapshot?.selectedObjectIds ?? [];
  assistantResponseActive = true;
  setGuidedControlsDisabled();
  send("guided.takeover.start", {
    scope: selectedIds.length ? "selection" : "current_question",
  });
});
elements.guidedContinue.addEventListener("click", () => sendGuidedCommand("continue"));
elements.guidedWhy.addEventListener("click", () => sendGuidedCommand("why"));
elements.guidedAlternative.addEventListener("click", () => sendGuidedCommand("alternative"));
elements.guidedTakeBack.addEventListener("click", () => sendGuidedCommand("take_back"));

elements.connect.addEventListener("click", connect);
elements.microphone.addEventListener("click", () => toggleMicrophone().catch((error) => setStatus(error.message)));
elements.finish.addEventListener("click", () => finishInterview().catch((error) => setStatus(error.message)));
elements.disconnect.addEventListener("click", disconnect);
