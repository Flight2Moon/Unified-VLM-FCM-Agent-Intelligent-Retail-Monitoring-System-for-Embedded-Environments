# VLM Explainability Update

This build adds GPU-server-side explainability for visual relation extraction.

## New web pages

- `/dashboard/events/{event_id}`: human-readable event detail page.
- `/api/events/{event_id}/explain`: JSON payload for VLM reasoning/evidence.
- `/api/events/{event_id}/graph`: vis-network compatible node/edge graph data.
- `/api/events/{event_id}/logs`: processing-stage timeline.

## New stored artifacts per event

Inside each event's extracted directory:

- `vlm_debug/*_prompt.txt`: exact prompt sent to the VLM.
- `vlm_debug/*_response.json`: raw Ollama response wrapper.
- `vlm_debug/*_parsed.json`: parsed relation JSON returned by the VLM.
- `result.json`: now includes `relations.relation_explanations` and `explainability`.

## New DB table

- `event_logs`: stores processing stages such as `queued`, `entities_normalized`, `vlm_relation_start`, `vlm_relation_done`, `scored`, and `done`.

## Dashboard changes

- Recent event IDs now open the event detail page.
- Each relation explanation shows:
  - final subject → relation → object edge,
  - VLM evidence strings,
  - why the edge was kept after validation/consolidation,
  - geometry evidence for the same entity pair,
  - prompt/response debug artifact links,
  - dropped competing edges.

## Notes

The graph page uses `vis-network` from a CDN. If the browser cannot access the CDN, the page falls back to rendering raw graph JSON.
