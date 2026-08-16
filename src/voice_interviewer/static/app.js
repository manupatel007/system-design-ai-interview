const elements = {
  status: document.querySelector("#status"),
  connect: document.querySelector("#connect"),
  microphone: document.querySelector("#microphone"),
  finish: document.querySelector("#finish"),
  disconnect: document.querySelector("#disconnect"),
  problem: document.querySelector("#problem"),
  glossary: document.querySelector("#glossary"),
  candidate: document.querySelector("#candidate"),
  interviewer: document.querySelector("#interviewer"),
  events: document.querySelector("#events"),
  interviewPhase: document.querySelector("#interview-phase"),
  currentQuestion: document.querySelector("#current-question"),
  evidenceCount: document.querySelector("#evidence-count"),
  rubricCount: document.querySelector("#rubric-count"),
  coveredTopics: document.querySelector("#covered-topics"),
  rubricSummary: document.querySelector("#rubric-summary"),
  interviewJson: document.querySelector("#interview-json"),
  feedback: document.querySelector("#interview-feedback"),
  feedbackSummary: document.querySelector("#feedback-summary"),
  feedbackStrengths: document.querySelector("#feedback-strengths"),
  feedbackImprovements: document.querySelector("#feedback-improvements"),
  feedbackNotDiscussed: document.querySelector("#feedback-not-discussed"),
  diagramSummary: document.querySelector("#diagram-summary"),
  diagramJson: document.querySelector("#diagram-json"),
  clear: document.querySelector("#clear"),
};

let socket;
let mediaStream;
let audioContext;
let captureNode;
let captureWorkletLoaded = false;
let microphoneActive = false;
let interviewCompleted = false;
const playbackSources = new Set();
let latestDiagramSnapshot = window.__diagramSnapshot ?? null;

function setStatus(text, connected = false) {
  elements.status.textContent = text;
  elements.status.classList.toggle("connected", connected);
}

function logEvent(event) {
  const item = document.createElement("li");
  item.textContent = `${event.sequence ?? "-"} ${event.type}`;
  elements.events.prepend(item);
  while (elements.events.children.length > 80) elements.events.lastChild.remove();
}

function send(type, payload = {}) {
  if (socket?.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ type, payload }));
  }
}

function connect() {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  const sessionId = crypto.randomUUID();
  ensureAudioContext().resume().catch(() => {});
  socket = new WebSocket(`${scheme}://${location.host}/ws/interview/${sessionId}`);
  socket.binaryType = "arraybuffer";
  setStatus("Connecting...");

  socket.addEventListener("open", () => {
    setStatus("Connected", true);
    elements.connect.disabled = true;
    elements.microphone.disabled = false;
    interviewCompleted = false;
    elements.finish.disabled = false;
    elements.finish.textContent = "Finish interview";
    elements.disconnect.disabled = false;
    elements.feedback.hidden = true;
    send("session.configure", {
      problem: elements.problem.value,
      glossary: elements.glossary.value.split(",").map((term) => term.trim()).filter(Boolean),
    });
    if (latestDiagramSnapshot) send("canvas.snapshot", latestDiagramSnapshot);
  });

  socket.addEventListener("message", ({ data }) => {
    if (typeof data !== "string") return;
    const event = JSON.parse(data);
    logEvent(event);
    const payload = event.payload ?? {};
    if (event.type === "candidate.transcript.final") elements.candidate.textContent = payload.text;
    if (event.type === "assistant.text.final") elements.interviewer.textContent = payload.text;
    if (event.type === "assistant.audio.chunk") playPcm(payload.audio, payload.sampleRate);
    if (event.type === "assistant.interrupted") stopPlayback();
    if (event.type === "interview.state") renderInterviewState(payload);
    if (event.type === "interview.feedback") renderFeedback(payload);
    if (event.type === "error") {
      setStatus(`Error: ${payload.message ?? payload.code}`);
      if (socket?.readyState === WebSocket.OPEN && !interviewCompleted) {
        elements.finish.disabled = false;
      }
    }
  });

  socket.addEventListener("close", () => resetConnection("Disconnected"));
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
  elements.microphone.textContent = "Stop microphone";
}

async function stopMicrophone() {
  if (!microphoneActive) return;
  send("audio.flush");
  captureNode?.disconnect();
  mediaStream?.getTracks().forEach((track) => track.stop());
  captureNode = undefined;
  mediaStream = undefined;
  microphoneActive = false;
  elements.microphone.textContent = "Start microphone";
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
  send("interview.finish");
}

function resetConnection(status) {
  setStatus(status);
  elements.connect.disabled = false;
  elements.microphone.disabled = true;
  elements.finish.disabled = true;
  elements.finish.textContent = "Finish interview";
  elements.disconnect.disabled = true;
  stopPlayback();
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
  source.start();
}

function stopPlayback() {
  playbackSources.forEach((source) => {
    try { source.stop(); } catch (_) { /* already stopped */ }
  });
  playbackSources.clear();
}

function renderDiagram(snapshot) {
  const delta = snapshot.delta?.summary ? ` - ${snapshot.delta.summary}` : "";
  elements.diagramSummary.textContent =
    `${snapshot.nodes.length} components | ${snapshot.edges.length} relationships${delta}`;
  elements.diagramJson.textContent = JSON.stringify(snapshot, null, 2);
}

function renderInterviewState(state) {
  const rubric = state.rubric ?? [];
  const demonstrated = rubric.filter((item) => item.level === "demonstrated").length;
  const someEvidence = rubric.filter((item) => item.level === "some_evidence").length;
  interviewCompleted = Boolean(state.completed);
  elements.interviewPhase.textContent = humanize(state.phase ?? "not_started");
  elements.currentQuestion.textContent =
    state.currentQuestion?.text ?? (state.completed ? "Interview complete." : "Listening...");
  elements.evidenceCount.textContent = String(state.evidenceCount ?? 0);
  elements.rubricCount.textContent = `${demonstrated + someEvidence} / ${rubric.length || 9}`;
  elements.coveredTopics.textContent = state.coveredTopics?.length
    ? `Covered: ${state.coveredTopics.map(humanize).join(", ")}`
    : "No topics covered yet.";
  elements.rubricSummary.textContent =
    `${demonstrated} demonstrated | ${someEvidence} with some evidence`;
  elements.interviewJson.textContent = JSON.stringify(state, null, 2);
  if (state.feedback) renderFeedback(state.feedback);
  if (state.completed) {
    elements.finish.disabled = true;
    elements.finish.textContent = "Interview complete";
    elements.microphone.disabled = true;
  }
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

elements.connect.addEventListener("click", connect);
elements.microphone.addEventListener("click", () => toggleMicrophone().catch((error) => setStatus(error.message)));
elements.finish.addEventListener("click", () => finishInterview().catch((error) => setStatus(error.message)));
elements.disconnect.addEventListener("click", disconnect);
