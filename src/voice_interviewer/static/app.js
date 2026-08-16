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
  canvas: document.querySelector("#canvas"),
  clear: document.querySelector("#clear"),
};

let socket;
let mediaStream;
let audioContext;
let captureNode;
let microphoneActive = false;
const playbackSources = new Set();

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
  setStatus("Connecting…");

  socket.addEventListener("open", () => {
    setStatus("Connected", true);
    elements.connect.disabled = true;
    elements.microphone.disabled = false;
    elements.disconnect.disabled = false;
    send("session.configure", {
      problem: elements.problem.value,
      glossary: elements.glossary.value.split(",").map((term) => term.trim()).filter(Boolean),
    });
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

const drawing = (() => {
  const context = elements.canvas.getContext("2d");
  context.lineWidth = 3;
  context.lineCap = "round";
  context.strokeStyle = "#6ee7b7";
  let active = false;
  let lastSignal = 0;

  function point(event) {
    const bounds = elements.canvas.getBoundingClientRect();
    return {
      x: (event.clientX - bounds.left) * (elements.canvas.width / bounds.width),
      y: (event.clientY - bounds.top) * (elements.canvas.height / bounds.height),
    };
  }

  elements.canvas.addEventListener("pointerdown", (event) => {
    active = true;
    const current = point(event);
    context.beginPath();
    context.moveTo(current.x, current.y);
    elements.canvas.setPointerCapture(event.pointerId);
  });

  elements.canvas.addEventListener("pointermove", (event) => {
    if (!active) return;
    const current = point(event);
    context.lineTo(current.x, current.y);
    context.stroke();
    if (performance.now() - lastSignal > 250) {
      send("canvas.activity", { diagramDelta: "added or adjusted elements on the canvas" });
      lastSignal = performance.now();
    }
  });

  elements.canvas.addEventListener("pointerup", () => {
    active = false;
    send("canvas.activity", { diagramDelta: "finished a canvas edit" });
  });

  elements.clear.addEventListener("click", () => {
    context.clearRect(0, 0, elements.canvas.width, elements.canvas.height);
    send("canvas.activity", { diagramDelta: "cleared the canvas" });
  });
})();

elements.connect.addEventListener("click", connect);
elements.microphone.addEventListener("click", () => toggleMicrophone().catch((error) => setStatus(error.message)));
elements.disconnect.addEventListener("click", disconnect);
