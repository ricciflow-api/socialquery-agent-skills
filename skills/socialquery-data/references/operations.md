# Operations and errors

The public catalog at `https://socialquery.dev/v1/meta/endpoints` returns `data.endpoints`. Each entry has an `id`, `method`, `/v1/...` path, `creditCost`, `launchStatus`, and `params`. Optional `oneOfParameters` lists groups where at least one named input is required. Inspect the operation before sending data requests. Different platforms have different paging inputs and response objects.

| Operation | Example | Cost |
| --- | --- | --- |
| Discovery | `discover --platform hackernews` | Free |
| Inspect | `inspect get_hackernews_search` | Free |
| Search | `call get_hackernews_search --params '{"query":"developer tools","hitsPerPage":10}' --max-credits 1` | Catalog cost; currently 1 |
| Profile | `call get_github_profile --params '{"handle":"octocat"}' --max-credits 1` | Catalog cost; currently 1 |
| Balance | `balance` | Free; key required |

Parameters accept strings, finite numbers, and booleans. For a parameter documented as serialized JSON, supply a JSON string. The helper only substitutes simple identifier path parameters and rejects URL traversal. It does not expose arbitrary URLs, credential headers, POST requests, or automatic retries.

The `max-credits` check uses the current catalog's base price. Optional enrichments and price changes can affect actual billing; it is not a server-enforced spending cap. Read `credits_used` after a call and retain the remaining task budget.

- 400/422: inspect required inputs; do not repeat the same invalid call.
- 401/403: correct local credentials or access before trying again.
- 402: insufficient credits; do not retry or purchase credits implicitly.
- 429: stop and respect the rate limit before a deliberate retry.
- 502/503/504: provider/service failure or unavailability; report the gap rather than inventing results.

The response envelope includes `success`, `data`, `request_id`, `credits_used`, `credits_remaining`, and `cached`. A cached result may predate collection. A failed HTTP request reports its status and request ID without echoing a potentially private error body.
