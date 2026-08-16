# Structured Excalidraw Canvas

## Objective

The browser embeds the actual MIT-licensed Excalidraw editor while keeping the interview backend independent of Excalidraw's internal scene format. Candidates get familiar drawing, text, arrow, grouping, selection, import, and export tools; the LLM receives a bounded semantic model rather than pixels or the full scene document.

## Data Flow

```text
Excalidraw elements + app state
  -> browser normalizer
  -> semantic snapshot + delta
  -> canvas.snapshot WebSocket control event
  -> backend validation and limits
  -> session diagram state
  -> compact diagramSnapshot in LLM context
```

The browser bundle is built offline into `src/voice_interviewer/static/excalidraw`. No CDN or runtime internet access is required.

## Extracted Model

Each snapshot contains:

- `nodes`: identifier, Excalidraw shape, inferred system-design role, bound label, geometry, and group IDs.
- `edges`: identifier, arrow/line shape, bound label, source and target bindings, and group IDs.
- `groups`: group identifier and normalized member identifiers.
- `selectedObjectIds`: selected semantic node or edge identifiers.
- `delta`: added, updated, and removed identifiers plus a human-readable semantic summary.
- `revision`: monotonically increasing client scene revision.

Bound Excalidraw text becomes the label of its container or connector instead of an independent node. Deleted elements are excluded. Arrays and identifiers are deterministically sorted so viewport changes do not create false scene changes.

## Role Inference

The browser derives compact roles from labels:

| Example labels | Role |
| --- | --- |
| Redis, cache, Memcached | `cache` |
| Kafka, queue, SQS | `queue` |
| PostgreSQL, database, Cassandra | `database` |
| API, worker, service | `service` |
| Load balancer, gateway, CDN | `load_balancer` |
| Browser, client, mobile | `client` |
| S3, blob, bucket | `object_storage` |

Unmatched shapes remain `component`; unbound text is `annotation`. Excalidraw `customData.systemDesignRole` takes precedence when a future semantic palette supplies an explicit role.

Role inference is a convenience for grounding, not scoring evidence. Interview evaluation should rely on what the candidate says and connects, and should preserve uncertainty when a label is ambiguous.

## Semantic Deltas

Snapshots are fingerprinted without volatile Excalidraw fields. A 350 ms debounce collapses pointer movement and text editing bursts. The normalizer compares nodes, edges, and groups by ID and produces messages such as:

```text
Added Redis
Connected API to PostgreSQL
Updated payment service
Removed a diagram element
Diagram changes: added 2, updated 1
```

Selection-only updates are synchronized but do not reset the backend canvas-quiet timer.

## Backend Validation

`DiagramSnapshot.from_payload` enforces:

- Schema version `1`.
- At most 250 nodes, 500 edges, and 100 groups.
- Bounded selection, group-membership, and delta reference arrays.
- Unique bounded entity identifiers.
- Numeric geometry and bounded labels.
- Edge bindings that reference existing nodes.
- Group membership that agrees in both the object and group projections.
- Selections that reference semantic nodes or edges, never bound text.
- Added and updated delta IDs that exist in the current snapshot, removed IDs that do not, and disjoint delta categories.
- Typed arrays for groups, selections, and deltas.

Invalid snapshots emit `error` with code `invalid_diagram` and do not replace the last accepted scene. Accepted snapshots emit `canvas.synced` with revision and entity counts.

## LLM Context

Geometry and visual styling remain available in session state but are omitted from the prompt. The compact provider payload includes only:

- Node ID, role, shape, and label.
- Edge ID, source, target, shape, and label.
- Group membership.
- Current selection.

This keeps provider prompts small and makes diagram evidence auditable. Diagram labels and roles also enrich the local Whisper vocabulary prompt.

## Frontend Development

Requirements:

- Node.js 22 or newer.
- pnpm.
- All caches and the content-addressable store on `F:`.

```powershell
.\scripts\build_frontend.ps1
```

The script performs a frozen install, runs the pure scene-normalizer tests, and rebuilds the production bundle. Runtime users do not need Node because the built assets are checked into the scaffold.

## Tests

- `frontend/src/diagram.test.js` covers labels, bindings, roles, groups, selection, fingerprints, and semantic deltas.
- `tests/test_diagram.py` covers validation, compact prompt projection, references, and duplicate IDs.
- `tests/test_pipeline_diagram.py` covers WebSocket control handling, synchronization, STT glossary enrichment, and invalid scene errors.
- `tests/test_server.py` confirms the built Excalidraw bundle and `canvas.synced` path are served end to end.
