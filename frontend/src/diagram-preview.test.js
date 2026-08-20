import assert from "node:assert/strict";
import test from "node:test";

import { normalizeScene } from "./diagram.js";

test("excludes browser-only AI preview elements from the semantic snapshot", () => {
  const scene = normalizeScene([
    element("api", "rectangle", { customData: { label: "API" } }),
    element("ai-note", "text", {
      text: "AI tutor suggestion",
      customData: { author: "ai", aiPreview: true },
    }),
    element("ai-cache", "rectangle", {
      customData: { author: "ai", aiPreview: true },
    }),
  ]);

  assert.deepEqual(scene.nodes.map((node) => node.id), ["api"]);
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
