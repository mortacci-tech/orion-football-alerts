# Development guardrails

- Keep the runtime deterministic and independent from external AI services.
- Treat the CBF as the primary schedule source.
- Keep delivery integrations outside this package and CLI.
- Preserve ledger-based idempotency for generated alerts.
- Do not add automatic retries or accept delivery recipients on the command line.
- Do not commit credentials, personal data, runtime state, downloaded documents, or local paths.
- Changes to schedulers, third-party delivery, or other products require separate review.
- Never invent dates, times, venues, or broadcasters.
