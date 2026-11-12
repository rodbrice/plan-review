# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `plan-review` command: reads `terraform show -json` output from a file or standard
  input, prints a plain-text report and exits 0, 1 (blocking finding) or 2 (unusable
  input or arguments).
- Typed model of the plan JSON (pydantic), with checks on `format_version` and on the
  action lists, and helpers for values known only after apply and sensitive values.
- Classification of each change: no-op, create, read, update, delete, forget, and
  replacement in both orders (delete then create, create then delete).
- Rule R1: a stateful resource is destroyed. Rule R2: a stateful resource is replaced,
  with the reason Terraform gives and the attributes that forced it.
- Explicit list of stateful AWS resource types used by R1 and R2.

- Project scaffold: `pyproject.toml` managed with uv, ruff, mypy in strict mode, pytest.
- Continuous integration: lint, type check, tests, and a job that verifies the sample
  plans match their Terraform sources.
- Six sample Terraform plans generated without an AWS account, with the script that
  regenerates them and a test that loads them.
- ADR-0001: the tool reviews the plan delta, not the state.
