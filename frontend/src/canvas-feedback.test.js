import assert from "node:assert/strict";
import test from "node:test";

import {
  buildCanvasFeedbackOverlays,
  isCanvasFeedbackElement,
  removeCanvasFeedback,
} from "./canvas-feedback.js";

test("builds a numbered outline around multiple referenced components", () => {
  const elements = [
    element("api", "rectangle", 100, 80, 160, 80),
    element("worker", "rectangle", 340, 200, 180, 90),
  ];

  const result = buildCanvasFeedbackOverlays(
    elements,
    [
      {
        kind: "issue",
        label: "Boundary is ambiguous",
        objectIds: ["api", "worker"],
        displayIndex: 2,
      },
    ],
    "feedback-7",
  );

  assert.equal(result.skeletons.length, 2);
  assert.deepEqual(result.targetIds, ["api", "worker"]);
  assert.equal(result.skeletons[1].label.text, "2");
  assert.ok(result.skeletons[0].x < 100);
  assert.ok(result.skeletons[0].x + result.skeletons[0].width > 520);
  assert.ok(result.skeletons.every(isCanvasFeedbackElement));
});

test("gives a straight relationship enough area to remain visible", () => {
  const arrow = {
    ...element("api-db", "arrow", 200, 140, 200, 0),
    points: [
      [0, 0],
      [200, 0],
    ],
  };

  const result = buildCanvasFeedbackOverlays(
    [arrow],
    [{ kind: "issue", label: "Unlabelled relation", objectIds: ["api-db"] }],
    "feedback-8",
  );

  assert.ok(result.skeletons[0].height >= 68);
});

test("ignores unknown targets and removes feedback without deleting proposals", () => {
  const candidate = element("api", "rectangle", 0, 0, 100, 60);
  const feedback = {
    ...element("feedback", "rectangle", 0, 0, 100, 60),
    customData: { aiPreview: true, aiCanvasFeedback: true },
  };
  const proposal = {
    ...element("proposal", "rectangle", 0, 0, 100, 60),
    customData: { aiPreview: true, aiProposalId: "proposal-1" },
  };

  const result = buildCanvasFeedbackOverlays(
    [candidate],
    [{ kind: "issue", label: "Missing", objectIds: ["unknown"] }],
    "feedback-9",
  );

  assert.deepEqual(result, { skeletons: [], targetIds: [] });
  assert.deepEqual(
    removeCanvasFeedback([candidate, feedback, proposal]).map((item) => item.id),
    ["api", "proposal"],
  );
});

function element(id, type, x, y, width, height) {
  return { id, type, x, y, width, height, isDeleted: false };
}
