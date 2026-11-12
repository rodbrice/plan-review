# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Project scaffold: `pyproject.toml` managed with uv, ruff, mypy in strict mode, pytest.
- Continuous integration: lint, type check, tests, and a job that verifies the sample
  plans match their Terraform sources.
- Six sample Terraform plans generated without an AWS account, with the script that
  regenerates them and a test that loads them.
- ADR-0001: the tool reviews the plan delta, not the state.
