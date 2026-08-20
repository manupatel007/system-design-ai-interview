const AI_STROKE = "#a855f7";
const AI_FILL = "#7e22ce";
const OUTLINE_PADDING = 16;
const MIN_OUTLINE_SIZE = 36;
const BADGE_SIZE = 34;

export function isCanvasFeedbackElement(element) {
  return element.customData?.aiCanvasFeedback === true;
}

export function removeCanvasFeedback(elements) {
  return elements.filter((element) => !isCanvasFeedbackElement(element));
}

export function buildCanvasFeedbackOverlays(elements, references, feedbackId) {
  const visibleElements = elements.filter(
    (element) => !element.isDeleted && !element.customData?.aiPreview,
  );
  const elementsById = new Map(visibleElements.map((element) => [element.id, element]));
  const skeletons = [];
  const targetIds = [];

  for (const [index, reference] of references.slice(0, 3).entries()) {
    const targets = [...new Set(reference.objectIds ?? [])]
      .map((identifier) => elementsById.get(identifier))
      .filter(Boolean);
    if (!targets.length) continue;
    const bounds = combinedBounds(targets);
    const displayIndex = Number(reference.displayIndex) || index + 1;
    const metadata = {
      author: "ai",
      aiPreview: true,
      aiCanvasFeedback: true,
      aiFeedbackId: feedbackId,
      aiReferenceIndex: displayIndex,
      aiReferenceKind: reference.kind ?? "issue",
    };
    const outline = paddedBounds(bounds);
    const identifier = `${feedbackId}-${displayIndex}`.replaceAll(/[^a-zA-Z0-9-]/g, "");
    skeletons.push(
      {
        type: "rectangle",
        id: `ai-feedback-${identifier}-outline`,
        ...outline,
        strokeColor: AI_STROKE,
        backgroundColor: "transparent",
        strokeStyle: "dashed",
        strokeWidth: 3,
        roughness: 1,
        opacity: 88,
        roundness: { type: 3 },
        locked: true,
        customData: { ...metadata, aiPreviewKind: "feedback-outline" },
      },
      {
        type: "ellipse",
        id: `ai-feedback-${identifier}-badge`,
        x: outline.x - BADGE_SIZE / 2,
        y: outline.y - BADGE_SIZE / 2,
        width: BADGE_SIZE,
        height: BADGE_SIZE,
        label: {
          text: String(displayIndex),
          fontSize: 17,
          strokeColor: "#ffffff",
        },
        strokeColor: AI_STROKE,
        backgroundColor: AI_FILL,
        fillStyle: "solid",
        strokeWidth: 2,
        roughness: 1,
        opacity: 96,
        locked: true,
        customData: { ...metadata, aiPreviewKind: "feedback-badge" },
      },
    );
    targetIds.push(...targets.map((element) => element.id));
    for (const target of targets) {
      for (const binding of [target.startBinding, target.endBinding]) {
        if (binding?.elementId && elementsById.has(binding.elementId)) {
          targetIds.push(binding.elementId);
        }
      }
    }
  }

  return { skeletons, targetIds: [...new Set(targetIds)] };
}

function combinedBounds(elements) {
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

function paddedBounds(bounds) {
  const width = Math.max(bounds.width, MIN_OUTLINE_SIZE);
  const height = Math.max(bounds.height, MIN_OUTLINE_SIZE);
  const centerX = bounds.x + bounds.width / 2;
  const centerY = bounds.y + bounds.height / 2;
  return {
    x: Math.round(centerX - width / 2 - OUTLINE_PADDING),
    y: Math.round(centerY - height / 2 - OUTLINE_PADDING),
    width: Math.round(width + OUTLINE_PADDING * 2),
    height: Math.round(height + OUTLINE_PADDING * 2),
  };
}
