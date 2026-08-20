import assert from "node:assert/strict";
import test from "node:test";

import {
  acceptAiProposal,
  buildStructuredAiProposal,
  isAiPreviewElement,
  removeAiProposal,
} from "./ai-preview.js";

test("builds a scoped structured proposal beside the selected component", () => {
  const elements = [
    component("api", 20, 40),
    component("db", 650, 40),
  ];
  const proposal = buildStructuredAiProposal(
    elements,
    {
      kind: "scoped",
      title: "Add a cache",
      summary: "Validate hit rate and fallback behavior.",
      nodes: [
        { id: "cache", label: "Read Cache", role: "cache", layer: 1 },
      ],
      edges: [
        {
          id: "api-cache",
          label: "lookup",
          sourceId: "api",
          targetId: "cache",
        },
      ],
    },
    ["api"],
    { centerX: 400, centerY: 300 },
    "proposal-1",
  );

  const proposedNode = proposal.skeletons.find(
    (element) => element.customData.aiProposalEntityId === "cache",
  );
  assert.equal(proposal.kind, "scoped");
  assert.equal(proposal.anchorIds[0], "api");
  assert.match(proposal.description, /fallback/);
  assert.ok(proposedNode.x > elements[0].x + elements[0].width);
  assert.ok(
    proposal.skeletons.some(
      (element) => element.customData.aiPreviewKind === "connector",
    ),
  );
  assert.ok(proposal.skeletons.every(isAiPreviewElement));
});

test("builds a new proposal from an accepted AI component", () => {
  const acceptedLoadBalancer = {
    ...component("ai-load-balancer", 260, 40),
    customData: {
      author: "ai",
      aiPreview: true,
      aiPreviewKind: "component",
      aiPreviewStatus: "accepted",
      label: "Load Balancer",
    },
  };
  const proposal = buildStructuredAiProposal(
    [component("client", 20, 40), acceptedLoadBalancer],
    {
      kind: "scoped",
      title: "Continue the request path",
      nodes: [
        { id: "api", label: "API Service", role: "service", layer: 1 },
      ],
      edges: [
        {
          id: "lb-api",
          label: "route",
          sourceId: "ai-load-balancer",
          targetId: "api",
        },
      ],
    },
    ["ai-load-balancer"],
    { centerX: 400, centerY: 300 },
    "proposal-follow-up",
  );

  const proposedNode = proposal.skeletons.find(
    (element) => element.customData.aiProposalEntityId === "api",
  );
  const connector = proposal.skeletons.find(
    (element) => element.customData.aiProposalEntityId === "lb-api",
  );
  assert.deepEqual(proposal.anchorIds, ["ai-load-balancer"]);
  assert.equal(connector.customData.aiSourceId, "ai-load-balancer");
  assert.equal(connector.customData.aiTargetId, proposedNode.id);
});

test("lays out a reference architecture in semantic layers", () => {
  const proposal = buildStructuredAiProposal(
    [component("candidate-api", 0, 0)],
    {
      kind: "reference_architecture",
      title: "Reference architecture",
      summary: "One illustrative design.",
      nodes: [
        { id: "client", label: "Client", role: "client", layer: 0 },
        { id: "api", label: "API", role: "service", layer: 1 },
        { id: "cache", label: "Cache", role: "cache", layer: 2 },
        { id: "store", label: "Store", role: "database", layer: 2 },
      ],
      edges: [
        {
          id: "client-api",
          label: "HTTPS",
          sourceId: "client",
          targetId: "api",
        },
        {
          id: "api-cache",
          label: "lookup",
          sourceId: "api",
          targetId: "cache",
        },
        {
          id: "invalid",
          label: "ignored",
          sourceId: "api",
          targetId: "missing",
        },
      ],
    },
    [],
    { centerX: 500, centerY: 300 },
    "proposal-2",
  );

  const nodes = new Map(
    proposal.skeletons
      .filter((element) => element.customData.aiPreviewKind === "component")
      .map((element) => [element.customData.aiProposalEntityId, element]),
  );
  const connectors = proposal.skeletons.filter(
    (element) => element.customData.aiPreviewKind === "connector",
  );
  assert.ok(nodes.get("client").x < nodes.get("api").x);
  assert.ok(nodes.get("api").x < nodes.get("cache").x);
  assert.equal(nodes.get("cache").x, nodes.get("store").x);
  assert.equal(connectors.length, 2);
  assert.ok(
    proposal.skeletons.some(
      (element) => element.customData.aiPreviewKind === "proposal-frame",
    ),
  );
});

test("accepts and removes only the targeted AI proposal", () => {
  const first = previewElement("first", "proposal-1");
  const second = previewElement("second", "proposal-2");
  const candidate = component("api", 20, 40);

  const accepted = acceptAiProposal([candidate, first, second], "proposal-1");

  assert.equal(accepted[1].customData.aiPreviewStatus, "accepted");
  assert.equal(accepted[1].customData.aiPreview, true);
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
