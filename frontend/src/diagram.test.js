import assert from "node:assert/strict";
import test from "node:test";

import { buildDelta, normalizeScene, sceneFingerprint } from "./diagram.js";

test("normalizes bound labels, bindings, groups, and selection", () => {
  const scene = normalizeScene(
    [
      element("api", "rectangle", { groupIds: ["backend"] }),
      element("api-label", "text", { containerId: "api", text: "API Service" }),
      element("db", "ellipse", { groupIds: ["backend"] }),
      element("db-label", "text", { containerId: "db", text: "PostgreSQL" }),
      element("api-db", "arrow", {
        startBinding: { elementId: "api" },
        endBinding: { elementId: "db" },
        groupIds: ["backend"],
      }),
      element("edge-label", "text", { containerId: "api-db", text: "SQL" }),
      element("deleted", "rectangle", { isDeleted: true }),
    ],
    { selectedElementIds: { db: true, "db-label": true } },
  );

  assert.deepEqual(scene.nodes.map(({ id, label, role }) => ({ id, label, role })), [
    { id: "api", label: "API Service", role: "service" },
    { id: "db", label: "PostgreSQL", role: "database" },
  ]);
  assert.deepEqual(scene.edges, [
    {
      id: "api-db",
      shape: "arrow",
      label: "SQL",
      sourceId: "api",
      targetId: "db",
      groupIds: ["backend"],
    },
  ]);
  assert.deepEqual(scene.groups, [
    { id: "backend", memberIds: ["api", "api-db", "db"] },
  ]);
  assert.deepEqual(scene.selectedObjectIds, ["db"]);
});

test("builds meaningful semantic deltas", () => {
  const previous = normalizeScene([element("api", "rectangle", { customData: { label: "API" } })]);
  const current = normalizeScene([
    element("api", "rectangle", { customData: { label: "API" } }),
    element("db", "ellipse", { customData: { label: "PostgreSQL" } }),
    element("api-db", "arrow", {
      startBinding: { elementId: "api" },
      endBinding: { elementId: "db" },
    }),
  ]);

  const delta = buildDelta(previous, current);

  assert.deepEqual(delta.addedIds, ["api-db", "db"]);
  assert.equal(delta.summary, "Diagram changes: added 2");
  assert.notEqual(sceneFingerprint(previous), sceneFingerprint(current));
});

test("describes a newly bound connector", () => {
  const previous = normalizeScene([
    element("api", "rectangle", { customData: { label: "API" } }),
    element("db", "ellipse", { customData: { label: "PostgreSQL" } }),
  ]);
  const current = normalizeScene([
    element("api", "rectangle", { customData: { label: "API" } }),
    element("db", "ellipse", { customData: { label: "PostgreSQL" } }),
    element("api-db", "arrow", {
      startBinding: { elementId: "api" },
      endBinding: { elementId: "db" },
    }),
  ]);

  assert.equal(buildDelta(previous, current).summary, "Connected API to PostgreSQL");
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
