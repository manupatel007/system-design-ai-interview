const elements = {
  status: document.querySelector("#status"),
  connect: document.querySelector("#connect"),
  microphone: document.querySelector("#microphone"),
  disconnect: document.querySelector("#disconnect"),
  problem: document.querySelector("#problem"),
  glossary: document.querySelector("#glossary"),
  candidate: document.querySelector("#candidate"),
  interviewer: document.querySelector("#interviewer"),
  events: document.querySelector("#events"),
  diagramSummary: document.querySelector("#diagram-summary"),
  diagramJson: document.querySelector("#diagram-json"),
  clear: document.querySelector("#clear"),
};

let socket;
let mediaStream;
let audioContext;
let captureNode;
let microphoneActive = false;
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
  socket = new WebSocket(`${scheme}://${location.host}/ws/interview/${sessionId}`);
  socket.binaryType = "arraybuffer";
  setStatus("Connecting...");

  socket.addEventListener("open", () => {
    setStatus("Connected", true);
    elements.connect.disabled = true;
    elements.microphone.disabled = false;
    elements.disconnect.disabled = false;
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
    if (event.type === "error") setStatus(`Error: ${payload.message ?? payload.code}`);
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
  audioContext = new AudioContext();
  await audioContext.audioWorklet.addModule("/static/pcm-worklet.js");
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
  await audioContext?.close();
  microphoneActive = false;
  elements.microphone.textContent = "Start microphone";
}

async function disconnect() {
  await stopMicrophone();
  socket?.close();
}

function resetConnection(status) {
  setStatus(status);
  elements.connect.disabled = false;
  elements.microphone.disabled = true;
  elements.disconnect.disabled = true;
  stopPlayback();
}

function playPcm(encodedAudio, sampleRate) {
  if (!encodedAudio) return;
  const bytes = Uint8Array.from(atob(encodedAudio), (character) => character.charCodeAt(0));
  const samples = new Int16Array(bytes.buffer);
  const context = audioContext && audioContext.state !== "closed" ? audioContext : new AudioContext();
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
elements.disconnect.addEventListener("click", disconnect);
