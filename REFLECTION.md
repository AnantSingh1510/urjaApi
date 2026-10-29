# Reflection

AI assistance was used for the portal investigation, implementation, tests and this write-up.

## What assumptions did you make?

The export became the catalog source after its count matched both its own `total` and the meter list. Network codes identify nodes within a level; names can change or disagree. The readings look cumulative and arrive at 30-minute intervals, so consumption comes from adjacent differences. `Asia/Kolkata` is an assumption because the timestamps have no offset. The June readings found during an October inspection also meant cache age had to stay separate from measurement age.

## Which part was most difficult, and how did you get unstuck?

Finding the useful data path took the most investigation. The initial HTML had an empty meter table, and the detail pages had two nameplate formats. The JavaScript linked by those pages revealed the JSON calls. The Transformers page then led to the signed bulk export, including the signing procedure. That one export replaced hundreds of possible detail requests. The remaining complication was the hierarchy: repeated codes with different parents meant a tree would lose information, so the API returns a graph with conflicts attached.

## If you had another day, what would you improve?

First, establish whether the portal supports date-range requests and observe a real session/key expiry. Those gaps matter more than another endpoint. More meter samples would help test the assumptions about cadence and register resets. After that, add refresh metrics and source timestamps, then persistence and spatial indexes if the dataset needs them. A UI could make the conflicting network relationships and missing intervals easier to inspect.

## What mistake did you make while solving this?

The first HTTP request didn't follow the redirect and returned an empty body. Following it reached the login page, but even after login the meter HTML still had no rows. The populated browser view showed why: the page loads records after hydration. That was a useful correction to the initial inspection approach. Python's local certificate setup caused another tooling failure; curl worked with verification enabled, and the final HTTPX setup passed live checks with its certificate bundle. Neither problem came from an empty or broken portal.

## If you were reviewing this submission, what would you criticise?

The biggest weakness is how much depends on an undocumented protocol and a small sample of live readings. Historical retrieval remains unverified. If the export starts paginating, the service fails rather than adapting automatically. Serial portal requests and per-process caches keep the implementation manageable, but they'll limit throughput. The graph reports contradictions without resolving them, and the consumption figures shouldn't be used for billing without confirming the register semantics and handling meter multipliers.
