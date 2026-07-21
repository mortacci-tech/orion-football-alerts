# Contributing

Contributions are welcome through GitHub issues and pull requests.

1. Create a focused branch and keep the runtime deterministic.
2. Do not commit credentials, personal data, downloaded PDFs, local runtime state, or production snapshots.
3. Add or update offline tests for behavior changes.
4. Run `python -m unittest discover -s tests -p 'test_*.py'` and `python -m compileall -q src tests`.
5. Explain source-format assumptions and failure behavior in the pull request.

Changes to delivery services or schedulers should be proposed separately from parser and alert-generation changes. By contributing, you agree that your contribution is licensed under the MIT License.
