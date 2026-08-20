const COMPONENT_TYPES = new Set(["rectangle", "ellipse", "diamond"]);
const ASSISTANT_ENTITY_KINDS = new Set(["component", "connector"]);
const PROPOSAL_KINDS = new Set(["scoped", "reference_architecture"]);
const AI_STROKE = "#a855f7";
const AI_FILL = "#e9d5ff";
const NODE_WIDTH = 210;
const NODE_HEIGHT = 92;
const COLUMN_GAP = 110;
const ROW_GAP = 52;
const FRAME_PADDING = 34;

export function isAiPreviewElement(element) {
  return element.customData?.aiPreview === true;
}

export function removeAiProposal(elements, proposalId) {
  return elements.filter(
    (element) => element.customData?.aiProposalId !== proposalId,
  );
}

export function acceptAiProposal(elements, proposalId) {
  return elements.map((element) => {
    if (element.customData?.aiProposalId !== proposalId) return element;
    return {
      ...element,
      locked: false,
      opacity: 100,
      strokeStyle: "solid",
      version: (element.version ?? 0) + 1,
      versionNonce: Math.floor(Math.random() * 2 ** 31),
      updated: Date.now(),
      customData: {
        ...element.customData,
        aiPreview: true,
        aiPreviewStatus: "accepted",
      },
    };
  });
}

export function buildStructuredAiProposal(
  elements,
  proposalPayload,
  anchorObjectIds,
  viewport,
  proposalId,
) {
  const proposal = normalizeProposal(proposalPayload);
  const metadata = {
    author: "ai",
    aiPreview: true,
    aiProposalId: proposalId,
    aiPreviewStatus: "proposed",
    aiProposalKind: proposal.kind,
  };
  if (!PROPOSAL_KINDS.has(proposal.kind)) {
    return {
      proposalId,
      kind: "none",
      title: "",
      description: "",
      anchorIds: [],
      skeletons: [],
    };
  }

  const visibleScene = elements.filter(
    (element) => !element.isDeleted && !element.customData?.aiCanvasFeedback,
  );
  const anchorableElements = visibleScene.filter(
    (element) =>
      !isAiPreviewElement(element) ||
      (
        element.customData?.aiPreviewStatus === "accepted" &&
        ASSISTANT_ENTITY_KINDS.has(element.customData?.aiPreviewKind)
      ),
  );
  const elementsById = new Map(
    anchorableElements.map((element) => [element.id, element]),
  );
  const anchorIds = [...new Set(anchorObjectIds ?? [])].filter((identifier) =>
    elementsById.has(identifier),
  );
  const anchors = anchorIds.map((identifier) => elementsById.get(identifier));
  const nodeLayouts = layoutNodes(
    proposal.nodes,
    visibleScene,
    anchors,
    viewport,
    proposal.kind,
  );
  const proposalNodeSceneIds = new Map(
    proposal.nodes.map((node) => [
      node.id,
      proposalElementId(proposalId, "node", node.id),
    ]),
  );
  const conceptBounds = new Map(
    anchorableElements
      .filter(isSemanticNodeElement)
      .map((element) => [element.id, elementBounds(element)]),
  );
  const nodeSkeletons = nodeLayouts.map((layout) => {
    const id = proposalNodeSceneIds.get(layout.node.id);
    const skeleton = proposalNode(layout, id, metadata);
    conceptBounds.set(layout.node.id, {
      x: skeleton.x,
      y: skeleton.y,
      width: skeleton.width,
      height: skeleton.height,
    });
    return skeleton;
  });

  const edgeSkeletons = proposal.edges.flatMap((edge) => {
    const source = conceptBounds.get(edge.sourceId);
    const target = conceptBounds.get(edge.targetId);
    if (!source || !target) return [];
    const points = connectionPoints(source, target);
    const skeleton = {
      type: "arrow",
      id: proposalElementId(proposalId, "edge", edge.id),
      x: points.start.x,
      y: points.start.y,
      width: points.end.x - points.start.x,
      height: points.end.y - points.start.y,
      points: [
        [0, 0],
        [
          points.end.x - points.start.x,
          points.end.y - points.start.y,
        ],
      ],
      endArrowhead: "arrow",
      strokeColor: AI_STROKE,
      strokeStyle: "dashed",
      strokeWidth: 2,
      roughness: 1,
      opacity: 76,
      locked: true,
      customData: {
        ...metadata,
        aiPreviewKind: "connector",
        aiProposalEntityId: edge.id,
        aiSourceId: proposalNodeSceneIds.get(edge.sourceId) ?? edge.sourceId,
        aiTargetId: proposalNodeSceneIds.get(edge.targetId) ?? edge.targetId,
        label: edge.label,
      },
    };
    if (edge.label) {
      skeleton.label = { text: edge.label, fontSize: 14 };
    }
    return [skeleton];
  });

  const frameBounds = combinedBounds(nodeSkeletons);
  const frameSkeletons = frameBounds
    ? [
        {
          type: "rectangle",
          id: proposalElementId(proposalId, "frame", "proposal"),
          x: frameBounds.x - FRAME_PADDING,
          y: frameBounds.y - FRAME_PADDING - 28,
          width: frameBounds.width + FRAME_PADDING * 2,
          height: frameBounds.height + FRAME_PADDING * 2 + 28,
          strokeColor: AI_STROKE,
          backgroundColor: "transparent",
          strokeStyle: "dashed",
          strokeWidth: 2,
          roughness: 1,
          opacity: 54,
          roundness: { type: 3 },
          locked: true,
          customData: {
            ...metadata,
            aiPreviewKind: "proposal-frame",
          },
        },
      ]
    : [];
  const noteAnchor =
    frameBounds ?? combinedBounds(anchors) ?? {
      x: viewport?.centerX ?? 320,
      y: viewport?.centerY ?? 220,
      width: 0,
      height: 0,
    };
  const note = {
    type: "text",
    id: proposalElementId(proposalId, "note", "title"),
    x: Math.round(noteAnchor.x),
    y: Math.round(noteAnchor.y - (frameBounds ? 55 : 46)),
    text: proposal.title,
    fontSize: 18,
    strokeColor: AI_STROKE,
    opacity: 92,
    locked: true,
    customData: {
      ...metadata,
      aiPreviewKind: "proposal-note",
    },
  };

  return {
    proposalId,
    kind: proposal.kind,
    title: proposal.title,
    description: proposal.summary || proposal.title,
    anchorIds,
    skeletons: [
      ...frameSkeletons,
      ...edgeSkeletons,
      ...nodeSkeletons,
      note,
    ],
  };
}

function normalizeProposal(payload) {
  const kind = String(payload?.kind ?? "none");
  const title = String(payload?.title ?? "").trim().slice(0, 120);
  const summary = String(payload?.summary ?? "").trim().slice(0, 360);
  const nodes = Array.isArray(payload?.nodes)
    ? payload.nodes.slice(0, 12).flatMap((node) => {
        const id = String(node?.id ?? "").trim();
        const label = String(node?.label ?? "").trim();
        if (!id || !label) return [];
        return [{
          id,
          label: label.slice(0, 80),
          role: String(node?.role ?? "other"),
          layer: Math.min(6, Math.max(0, Number(node?.layer) || 0)),
        }];
      })
    : [];
  const edges = Array.isArray(payload?.edges)
    ? payload.edges.slice(0, 18).flatMap((edge) => {
        const id = String(edge?.id ?? "").trim();
        const sourceId = String(edge?.sourceId ?? "").trim();
        const targetId = String(edge?.targetId ?? "").trim();
        if (!id || !sourceId || !targetId || sourceId === targetId) return [];
        return [{
          id,
          sourceId,
          targetId,
          label: String(edge?.label ?? "").trim().slice(0, 80),
        }];
      })
    : [];
  return { kind, title, summary, nodes, edges };
}

function layoutNodes(nodes, scene, anchors, viewport, kind) {
  if (!nodes.length) return [];
  const layers = new Map();
  for (const node of nodes) {
    const layerItems = layers.get(node.layer) ?? [];
    layerItems.push(node);
    layers.set(node.layer, layerItems);
  }
  const layerNumbers = [...layers.keys()].sort((left, right) => left - right);
  const minimumLayer = layerNumbers[0];
  const maximumRows = Math.max(
    ...layerNumbers.map((layer) => layers.get(layer).length),
  );
  const layoutHeight =
    maximumRows * NODE_HEIGHT + Math.max(0, maximumRows - 1) * ROW_GAP;
  const sceneBounds = combinedBounds(scene);
  const anchorBounds = combinedBounds(anchors);
  const maximumLayer = layerNumbers.at(-1);
  const layoutWidth =
    (maximumLayer - minimumLayer) * (NODE_WIDTH + COLUMN_GAP) + NODE_WIDTH;
  let originX;
  let originY;
  if (kind === "reference_architecture") {
    originX = sceneBounds
      ? sceneBounds.x + sceneBounds.width + 230
      : (viewport?.centerX ?? 480) - layoutWidth / 2;
    originY = sceneBounds
      ? sceneBounds.y
      : (viewport?.centerY ?? 320) - layoutHeight / 2;
  } else {
    const placementBounds = anchorBounds ?? sceneBounds;
    originX = placementBounds
      ? placementBounds.x + placementBounds.width + 150
      : (viewport?.centerX ?? 420) - NODE_WIDTH / 2;
    originY = placementBounds
      ? placementBounds.y + placementBounds.height / 2 - layoutHeight / 2
      : (viewport?.centerY ?? 280) - layoutHeight / 2;
  }
  let layouts = buildLayerLayouts(
    layers,
    layerNumbers,
    minimumLayer,
    originX,
    originY,
    maximumRows,
  );
  if (kind === "scoped") {
    for (let attempt = 0; attempt < 6; attempt += 1) {
      const occupied = layouts.some((layout) =>
        scene.some((element) =>
          rectanglesOverlap(
            {
              x: layout.x,
              y: layout.y,
              width: NODE_WIDTH,
              height: NODE_HEIGHT,
            },
            elementBounds(element),
            24,
          ),
        ),
      );
      if (!occupied) break;
      layouts = layouts.map((layout) => ({
        ...layout,
        y: layout.y + NODE_HEIGHT + ROW_GAP,
      }));
    }
  }
  return layouts;
}

function buildLayerLayouts(
  layers,
  layerNumbers,
  minimumLayer,
  originX,
  originY,
  maximumRows,
) {
  return layerNumbers.flatMap((layer) => {
    const items = layers.get(layer);
    const topOffset =
      (maximumRows - items.length) * (NODE_HEIGHT + ROW_GAP) / 2;
    return items.map((node, row) => ({
      node,
      x: Math.round(
        originX + (layer - minimumLayer) * (NODE_WIDTH + COLUMN_GAP),
      ),
      y: Math.round(originY + topOffset + row * (NODE_HEIGHT + ROW_GAP)),
    }));
  });
}

function proposalNode(layout, id, metadata) {
  return {
    type: shapeForRole(layout.node.role),
    id,
    x: layout.x,
    y: layout.y,
    width: NODE_WIDTH,
    height: NODE_HEIGHT,
    label: { text: layout.node.label, fontSize: 17 },
    strokeColor: AI_STROKE,
    backgroundColor: AI_FILL,
    fillStyle: "hachure",
    strokeStyle: "dashed",
    strokeWidth: 2,
    roughness: 1,
    opacity: 76,
    roundness: { type: 3 },
    locked: true,
    customData: {
      ...metadata,
      aiPreviewKind: "component",
      aiProposalEntityId: layout.node.id,
      systemDesignRole: layout.node.role,
      label: layout.node.label,
    },
  };
}

function isSemanticNodeElement(element) {
  return !["arrow", "line", "text"].includes(element.type);
}

function shapeForRole(role) {
  if (role === "database" || role === "object_storage") return "ellipse";
  if (role === "client" || role === "external") return "ellipse";
  return "rectangle";
}

function connectionPoints(source, target) {
  const sourceCenter = {
    x: source.x + source.width / 2,
    y: source.y + source.height / 2,
  };
  const targetCenter = {
    x: target.x + target.width / 2,
    y: target.y + target.height / 2,
  };
  const horizontalDistance = Math.abs(targetCenter.x - sourceCenter.x);
  const verticalDistance = Math.abs(targetCenter.y - sourceCenter.y);
  if (horizontalDistance >= verticalDistance) {
    const movesRight = targetCenter.x >= sourceCenter.x;
    return {
      start: {
        x: movesRight ? source.x + source.width : source.x,
        y: sourceCenter.y,
      },
      end: {
        x: movesRight ? target.x : target.x + target.width,
        y: targetCenter.y,
      },
    };
  }
  const movesDown = targetCenter.y >= sourceCenter.y;
  return {
    start: {
      x: sourceCenter.x,
      y: movesDown ? source.y + source.height : source.y,
    },
    end: {
      x: targetCenter.x,
      y: movesDown ? target.y : target.y + target.height,
    },
  };
}

function proposalElementId(proposalId, kind, entityId) {
  const proposalPart = safeIdentifier(proposalId).slice(0, 18);
  const entityPart = safeIdentifier(entityId).slice(0, 20);
  return (
    "ai-" +
    proposalPart +
    "-" +
    kind +
    "-" +
    entityPart +
    "-" +
    identifierHash(entityId)
  );
}

function safeIdentifier(value) {
  return (
    String(value ?? "proposal").replaceAll(/[^a-zA-Z0-9-]/g, "-") || "item"
  );
}

function identifierHash(value) {
  let hash = 2166136261;
  for (const character of String(value ?? "")) {
    hash ^= character.codePointAt(0);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(36);
}

function combinedBounds(elements) {
  if (!elements.length) return null;
  const bounds = elements.map(elementBounds);
  const minimumX = Math.min(...bounds.map((item) => item.x));
  const minimumY = Math.min(...bounds.map((item) => item.y));
  const maximumX = Math.max(...bounds.map((item) => item.x + item.width));
  const maximumY = Math.max(...bounds.map((item) => item.y + item.height));
  return {
    x: minimumX,
    y: minimumY,
    width: maximumX - minimumX,
    height: maximumY - minimumY,
  };
}

function elementBounds(element) {
  const points = Array.isArray(element.points) ? element.points : [];
  if (points.length) {
    const xValues = points.map((point) => element.x + Number(point[0] ?? 0));
    const yValues = points.map((point) => element.y + Number(point[1] ?? 0));
    const minimumX = Math.min(...xValues);
    const minimumY = Math.min(...yValues);
    return {
      x: minimumX,
      y: minimumY,
      width: Math.max(...xValues) - minimumX,
      height: Math.max(...yValues) - minimumY,
    };
  }
  const x = Math.min(element.x, element.x + element.width);
  const y = Math.min(element.y, element.y + element.height);
  return {
    x,
    y,
    width: Math.abs(element.width),
    height: Math.abs(element.height),
  };
}

function rectanglesOverlap(first, second, padding) {
  return !(
    first.x + first.width + padding < second.x ||
    second.x + second.width + padding < first.x ||
    first.y + first.height + padding < second.y ||
    second.y + second.height + padding < first.y
  );
}
