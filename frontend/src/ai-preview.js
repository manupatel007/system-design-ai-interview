const COMPONENT_TYPES = new Set(["rectangle", "ellipse", "diamond"]);
const AI_STROKE = "#a855f7";
const AI_FILL = "#e9d5ff";
const PROPOSAL_WIDTH = 230;
const PROPOSAL_HEIGHT = 104;
const VERTICAL_GAP = 54;

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
        aiPreviewStatus: "accepted",
      },
    };
  });
}

export function buildAiTutorProposal(
  elements,
  selectedElementIds,
  viewport,
  proposalId,
) {
  const candidateElements = elements.filter(
    (element) =>
      !element.isDeleted &&
      !isAiPreviewElement(element) &&
      COMPONENT_TYPES.has(element.type),
  );
  const selectedIds = new Set(
    Array.isArray(selectedElementIds)
      ? selectedElementIds
      : Object.keys(selectedElementIds ?? {}).filter(
          (identifier) => selectedElementIds[identifier],
        ),
  );
  const anchor =
    candidateElements.find((element) => selectedIds.has(element.id)) ??
    candidateElements.at(-1);
  const proposalMetadata = {
    author: "ai",
    aiPreview: true,
    aiProposalId: proposalId,
    aiPreviewStatus: "proposed",
  };
  const identifier = proposalId.replaceAll("-", "").slice(0, 12);

  if (!anchor) {
    const x = Math.round((viewport?.centerX ?? 300) - PROPOSAL_WIDTH / 2);
    const y = Math.round((viewport?.centerY ?? 220) - PROPOSAL_HEIGHT / 2);
    return {
      proposalId,
      anchorId: null,
      description: "AI tutor preview: draw or select a component for a contextual suggestion.",
      skeletons: [
        proposalNode({
          id: `ai-${identifier}-node`,
          x,
          y,
          label: "AI tutor preview\nSelect a component",
          metadata: proposalMetadata,
        }),
        proposalNote({
          id: `ai-${identifier}-note`,
          x,
          y: y - 44,
          text: "Purple elements represent AI-owned content",
          metadata: proposalMetadata,
        }),
      ],
    };
  }

  const anchorLabel = labelFor(anchor, elements);
  const location = proposalLocation(
    anchor,
    elements.filter((element) => !element.isDeleted),
  );
  const anchorCenterY = anchor.y + anchor.height / 2;
  const proposalCenterY = location.y + PROPOSAL_HEIGHT / 2;
  const arrowStartX = anchor.x + anchor.width + 12;
  const arrowEndX = location.x - 12;

  return {
    proposalId,
    anchorId: anchor.id,
    description: `Explore a cache or queue beside ${anchorLabel}, then discuss the trade-off.`,
    skeletons: [
      {
        type: "rectangle",
        id: `ai-${identifier}-highlight`,
        x: anchor.x - 12,
        y: anchor.y - 12,
        width: anchor.width + 24,
        height: anchor.height + 24,
        strokeColor: AI_STROKE,
        backgroundColor: "transparent",
        strokeStyle: "dashed",
        strokeWidth: 2,
        roughness: 1,
        opacity: 72,
        locked: true,
        customData: { ...proposalMetadata, aiPreviewKind: "highlight" },
      },
      proposalNode({
        id: `ai-${identifier}-node`,
        x: location.x,
        y: location.y,
        label: "AI proposal\nCache or queue?",
        metadata: {
          ...proposalMetadata,
          aiPreviewKind: "component",
          systemDesignRole: "cache",
          label: "AI proposal: Cache or queue?",
        },
      }),
      {
        type: "arrow",
        id: `ai-${identifier}-arrow`,
        x: arrowStartX,
        y: anchorCenterY,
        width: arrowEndX - arrowStartX,
        height: proposalCenterY - anchorCenterY,
        points: [
          [0, 0],
          [arrowEndX - arrowStartX, proposalCenterY - anchorCenterY],
        ],
        endArrowhead: "arrow",
        strokeColor: AI_STROKE,
        strokeStyle: "dashed",
        strokeWidth: 2,
        roughness: 1,
        opacity: 72,
        locked: true,
        customData: { ...proposalMetadata, aiPreviewKind: "connector" },
      },
      proposalNote({
        id: `ai-${identifier}-note`,
        x: location.x,
        y: location.y - 44,
        text: "AI tutor · validate need and failure mode",
        metadata: proposalMetadata,
      }),
    ],
  };
}

function proposalNode({ id, x, y, label, metadata }) {
  return {
    type: "rectangle",
    id,
    x,
    y,
    width: PROPOSAL_WIDTH,
    height: PROPOSAL_HEIGHT,
    label: { text: label, fontSize: 18 },
    strokeColor: AI_STROKE,
    backgroundColor: AI_FILL,
    fillStyle: "hachure",
    strokeStyle: "dashed",
    strokeWidth: 2,
    roughness: 1,
    opacity: 72,
    roundness: { type: 3 },
    locked: true,
    customData: { ...metadata, aiPreviewKind: metadata.aiPreviewKind ?? "component" },
  };
}

function proposalNote({ id, x, y, text, metadata }) {
  return {
    type: "text",
    id,
    x,
    y,
    text,
    fontSize: 16,
    strokeColor: AI_STROKE,
    opacity: 82,
    locked: true,
    customData: { ...metadata, aiPreviewKind: "note" },
  };
}

function proposalLocation(anchor, elements) {
  const location = {
    x: Math.round(anchor.x + anchor.width + 150),
    y: Math.round(anchor.y + anchor.height / 2 - PROPOSAL_HEIGHT / 2),
  };
  for (let attempt = 0; attempt < 6; attempt += 1) {
    const occupied = elements.some(
      (element) =>
        element.id !== anchor.id &&
        rectanglesOverlap(
          { ...location, width: PROPOSAL_WIDTH, height: PROPOSAL_HEIGHT },
          element,
          28,
        ),
    );
    if (!occupied) return location;
    location.y += PROPOSAL_HEIGHT + VERTICAL_GAP;
  }
  return location;
}

function rectanglesOverlap(first, second, padding) {
  return !(
    first.x + first.width + padding < second.x ||
    second.x + second.width + padding < first.x ||
    first.y + first.height + padding < second.y ||
    second.y + second.height + padding < first.y
  );
}

function labelFor(anchor, elements) {
  const explicitLabel = anchor.customData?.label?.trim();
  if (explicitLabel) return explicitLabel;
  const boundLabel = elements.find(
    (element) =>
      !element.isDeleted && element.type === "text" && element.containerId === anchor.id,
  );
  const text = String(boundLabel?.text ?? boundLabel?.originalText ?? "").trim();
  return text || "the selected component";
}
