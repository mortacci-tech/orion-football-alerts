# Architecture

Orion Football Alerts is a single deterministic Python package with no delivery or scheduling runtime.

```text
official CBF article/PDF or public fixture
                  |
                  v
        download and validation
                  |
                  v
      deterministic normalization
                  |
          full-candidate checks
                  |
        +---------+----------+
        |                    |
        v                    v
 atomic snapshot       source manifest
        |
        v
 previews, pregame text, and local alert plans
        |
        v
 idempotency ledger in the configured data directory
```

## Boundaries

- `futebol.py` owns source validation, parsing, normalization, rendering, state paths, and CLI dispatch.
- Packaged resources make fixture mode and the safe default configuration work after a normal wheel installation.
- The real-data refresh validates the complete candidate before replacing the active snapshot.
- Preview and alert commands read local normalized data and do not contact the network.
- Delivery and scheduling are intentionally outside the package boundary.

All mutable files live below `data_dir`. Repository fixtures and tests remain read-only and contain no runtime data.
