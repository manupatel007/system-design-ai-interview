import assert from "node:assert/strict";
import test from "node:test";

import { normalizeScene } from "./diagram.js";

test("separates accepted AI entities from candidate evidence", () => {
  const scene = normalizeScene(
    [
      element("api", "rectangle", { customData: { label: "API" } }),
      element("ai-proposed", "rectangle", {
        customData: {
          author: "ai",
          aiPreview: true,
          aiPreviewKind: "component",
          aiPreviewStatus: "proposed",
        },
      }),
      element("ai-lb", "rectangle", {
        customData: {
          author: "ai",
          aiPreview: true,
          aiPreviewKind: "component",
          aiPreviewStatus: "accepted",
          label: "Load Balancer",
          systemDesignRole: "load_balancer",
        },
      }),
      element("ai-lb-label", "text", {
        containerId: "ai-lb",
        text: "Regional Load Balancer",
        customData: { author: "ai", aiPreview: true },
      }),
      element("ai-api-lb", "arrow", {
        customData: {
          author: "ai",
          aiPreview: true,
          aiPreviewKind: "connector",
          aiPreviewStatus: "accepted",
          aiSourceId: "api",
          aiTargetId: "ai-lb",
          label: "HTTPS",
        },
      }),
      element("ai-frame", "rectangle", {
        customData: {
          author: "ai",
          aiPreview: true,
          aiPreviewKind: "proposal-frame",
          aiPreviewStatus: "accepted",
        },
      }),
    ],
    { selectedElementIds: { "ai-lb": true } },
  );

  assert.deepEqual(scene.nodes.map((node) => node.id), ["api"]);
  assert.deepEqual(
    scene.assistantLayer.nodes.map(({ id, label, role }) => ({
      id,
      label,
      role,
    })),
    [
      {
        id: "ai-lb",
        label: "Regional Load Balancer",
        role: "load_balancer",
      },
    ],
  );
  assert.deepEqual(scene.assistantLayer.edges, [
    {
      id: "ai-api-lb",
      shape: "arrow",
      label: "HTTPS",
      sourceId: "api",
      targetId: "ai-lb",
      groupIds: [],
    },
  ]);
  assert.deepEqual(scene.selectedObjectIds, ["ai-lb"]);
});

function element(id, type, overrides = {}) {
  return {
    id,
    type,
    x: 10,
    y: 20,
    width: 160,
    height: 80,
    groupIds: [],
    isDeleted: false,
    ...overrides,
  };
}
