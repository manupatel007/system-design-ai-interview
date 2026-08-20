import assert from "node:assert/strict";
import test from "node:test";

import {
  acceptAiProposal,
  buildAiTutorProposal,
  isAiPreviewElement,
  removeAiProposal,
} from "./ai-preview.js";

test("builds a contextual proposal beside the selected component", () => {
  const elements = [
    component("api", 20, 40),
    text("api-label", "api", "API Gateway"),
    component("db", 650, 40),
  ];

  const proposal = buildAiTutorProposal(
    elements,
    { api: true },
    { centerX: 400, centerY: 300 },
    "proposal-1",
  );

  assert.equal(proposal.anchorId, "api");
  assert.match(proposal.description, /API Gateway/);
  assert.deepEqual(
    proposal.skeletons.map((element) => element.customData.aiPreviewKind),
    ["highlight", "component", "connector", "note"],
  );
  assert.ok(proposal.skeletons.every(isAiPreviewElement));
  assert.ok(proposal.skeletons[1].x > elements[0].x + elements[0].width);
});

test("moves a proposal to avoid an occupied location", () => {
  const anchor = component("api", 20, 40);
  const occupied = component("worker", 330, 28);

  const proposal = buildAiTutorProposal(
    [anchor, occupied],
    { api: true },
    { centerX: 400, centerY: 300 },
    "proposal-2",
  );

  assert.ok(proposal.skeletons[1].y > occupied.y + occupied.height);
});

test("accepts and removes only the targeted AI proposal", () => {
  const first = previewElement("first", "proposal-1");
  const second = previewElement("second", "proposal-2");
  const candidate = component("api", 20, 40);

  const accepted = acceptAiProposal([candidate, first, second], "proposal-1");

  assert.equal(accepted[1].customData.aiPreviewStatus, "accepted");
  assert.equal(accepted[1].strokeStyle, "solid");
  assert.equal(accepted[1].locked, false);
  assert.deepEqual(
    removeAiProposal(accepted, "proposal-1").map((element) => element.id),
    ["api", "second"],
  );
});

function component(id, x, y) {
  return {
    id,
    type: "rectangle",
    x,
    y,
    width: 160,
    height: 80,
    isDeleted: false,
  };
}

function text(id, containerId, value) {
  return {
    id,
    type: "text",
    containerId,
    text: value,
    x: 0,
    y: 0,
    width: 100,
    height: 20,
    isDeleted: false,
  };
}

function previewElement(id, proposalId) {
  return {
    ...component(id, 0, 0),
    locked: true,
    opacity: 72,
    strokeStyle: "dashed",
    customData: {
      author: "ai",
      aiPreview: true,
      aiProposalId: proposalId,
      aiPreviewStatus: "proposed",
    },
  };
}
