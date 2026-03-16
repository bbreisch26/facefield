# Facefield Firefox Extension (v1)

Manual capture extension for Facebook interactions.

## Setup
1. Open Firefox and go to `about:debugging#/runtime/this-firefox`.
2. Click `Load Temporary Add-on...`.
3. Select `manifest.json` from this folder.
4. Open extension settings and configure:
   - API Base URL (default `http://localhost:8000`)
   - `X-API-Key` matching backend `SOCIAL_API_KEY`

## Use
1. Open a Facebook page/post with visible comments.
2. Click the extension action.
3. Click `Capture Current Page`.
4. Data is sent to `POST /api/social/captures`.

## Notes
- Collector is Facebook-first and heuristic-based.
- It runs one expansion pass for "view more" comment/reply controls.
- Instagram/X collectors are intentionally deferred.
