const CONNECTOR_TYPES = new Set(["arrow", "line"]);

export function normalizeScene(elements, appState = {}) {
  const visible = elements.filter(
    (element) => !element.isDeleted && element.customData?.aiPreview !== true,
  );
  const boundText = new Map();
  for (const element of visible) {
    if (element.type === "text" && element.containerId) {
      boundText.set(element.containerId, normalizeLabel(element.text ?? element.originalText));
    }
  }

  const nodes = visible
    .filter((element) => !CONNECTOR_TYPES.has(element.type))
    .filter((element) => element.type !== "text" || !element.containerId)
    .map((element) => normalizeNode(element, boundText))
    .sort(byIdentifier);
  const edges = visible
    .filter((element) => CONNECTOR_TYPES.has(element.type))
    .map((element) => normalizeEdge(element, boundText))
    .sort(byIdentifier);
  const groups = normalizeGroups([...nodes, ...edges]);
  const semanticIds = new Set([...nodes, ...edges].map((entity) => entity.id));
  const selectedObjectIds = Object.keys(appState.selectedElementIds ?? {})
    .filter((identifier) => semanticIds.has(identifier))
    .sort();

  return {
    version: 1,
    nodes,
    edges,
    groups,
    selectedObjectIds,
  };
}

export function buildDelta(previous, current) {
  const previousEntities = entitiesById(previous);
  const currentEntities = entitiesById(current);
  const addedIds = [...currentEntities.keys()]
    .filter((identifier) => !previousEntities.has(identifier))
    .sort();
  const removedIds = [...previousEntities.keys()]
    .filter((identifier) => !currentEntities.has(identifier))
    .sort();
  const updatedIds = [...currentEntities.keys()]
    .filter(
      (identifier) =>
        previousEntities.has(identifier) &&
        JSON.stringify(previousEntities.get(identifier)) !==
          JSON.stringify(currentEntities.get(identifier)),
    )
    .sort();
  return {
    addedIds,
    updatedIds,
    removedIds,
    summary: describeDelta(previous, current, { addedIds, updatedIds, removedIds }),
  };
}

export function sceneFingerprint(snapshot) {
  return JSON.stringify({
    nodes: snapshot.nodes,
    edges: snapshot.edges,
    groups: snapshot.groups,
    selectedObjectIds: snapshot.selectedObjectIds,
  });
}

function normalizeNode(element, boundText) {
  const label = normalizeLabel(
    element.customData?.label ??
      boundText.get(element.id) ??
      (element.type === "text" ? element.text ?? element.originalText : ""),
  );
  return {
    id: element.id,
    shape: element.type,
    role: inferRole(label, element.type, element.customData?.systemDesignRole),
    label,
    x: rounded(element.x),
    y: rounded(element.y),
    width: Math.max(0, rounded(element.width)),
    height: Math.max(0, rounded(element.height)),
    groupIds: [...new Set(element.groupIds ?? [])].sort(),
  };
}

function normalizeEdge(element, boundText) {
  return {
    id: element.id,
    shape: element.type,
    label: normalizeLabel(element.customData?.label ?? boundText.get(element.id) ?? ""),
    sourceId: element.startBinding?.elementId ?? null,
    targetId: element.endBinding?.elementId ?? null,
    groupIds: [...new Set(element.groupIds ?? [])].sort(),
  };
}

function normalizeGroups(entities) {
  const members = new Map();
  for (const entity of entities) {
    for (const groupId of entity.groupIds) {
      const groupMembers = members.get(groupId) ?? [];
      groupMembers.push(entity.id);
      members.set(groupId, groupMembers);
    }
  }
  return [...members.entries()]
    .map(([id, memberIds]) => ({ id, memberIds: [...new Set(memberIds)].sort() }))
    .sort(byIdentifier);
}

function entitiesById(snapshot) {
  if (!snapshot) return new Map();
  return new Map(
    [...snapshot.nodes, ...snapshot.edges, ...snapshot.groups].map((entity) => [
      entity.id,
      entity,
    ]),
  );
}

function describeDelta(previous, current, delta) {
  if (delta.addedIds.length === 1) {
    const edge = current.edges.find((item) => item.id === delta.addedIds[0]);
    if (edge?.sourceId && edge?.targetId) {
      return `Connected ${nodeName(current, edge.sourceId)} to ${nodeName(current, edge.targetId)}`;
    }
    const node = current.nodes.find((item) => item.id === delta.addedIds[0]);
    if (node) return `Added ${node.label || node.role}`;
  }
  if (delta.removedIds.length === 1) {
    const entity = previous?.nodes.find((item) => item.id === delta.removedIds[0]);
    return `Removed ${entity?.label || entity?.role || "a diagram element"}`;
  }
  if (delta.updatedIds.length === 1) {
    const node = current.nodes.find((item) => item.id === delta.updatedIds[0]);
    if (node) return `Updated ${node.label || node.role}`;
  }
  const parts = [];
  if (delta.addedIds.length) parts.push(`added ${delta.addedIds.length}`);
  if (delta.updatedIds.length) parts.push(`updated ${delta.updatedIds.length}`);
  if (delta.removedIds.length) parts.push(`removed ${delta.removedIds.length}`);
  return parts.length ? `Diagram changes: ${parts.join(", ")}` : "Updated diagram selection";
}

function nodeName(snapshot, identifier) {
  const node = snapshot.nodes.find((item) => item.id === identifier);
  return node?.label || node?.role || identifier;
}

function inferRole(label, shape, explicitRole) {
  if (typeof explicitRole === "string" && explicitRole.trim()) return explicitRole.trim();
  const normalized = label.toLowerCase();
  const rules = [
    ["cache", /\b(cache|redis|memcached)\b/],
    ["queue", /\b(queue|kafka|rabbitmq|sqs|pubsub|event bus)\b/],
    ["database", /\b(database|postgres(?:ql)?|mysql|mongodb|cassandra|dynamodb|sql|db)\b/],
    ["object_storage", /\b(s3|blob|object storage|bucket)\b/],
    ["load_balancer", /\b(load balancer|gateway|ingress|proxy|cdn)\b/],
    ["client", /\b(client|browser|mobile|user|device)\b/],
    ["service", /\b(service|api|server|worker|consumer|producer)\b/],
  ];
  for (const [role, pattern] of rules) {
    if (pattern.test(normalized)) return role;
  }
  return shape === "text" ? "annotation" : "component";
}

function normalizeLabel(value) {
  return typeof value === "string" ? value.trim().slice(0, 240) : "";
}

function rounded(value) {
  return Number.isFinite(value) ? Math.round(value) : 0;
}

function byIdentifier(left, right) {
  return left.id.localeCompare(right.id);
}
