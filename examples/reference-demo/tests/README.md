# Reference Demo — API Tests (PLACEHOLDER)

TODO: after the assembled config is pushed (`PUT /api/v1/configuration/bulk`), tests will:
1. Post sample business events via API.
2. Assert resulting journal postings, account balances, and continuous consolidation.
3. Verify drill-through (statement line → posting → event → source).

Requires a live Fynapse instance + credentials — never committed (see repo `.gitignore`).
