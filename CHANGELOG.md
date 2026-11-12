# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Rule R3: an IAM policy grants a new wildcard action or resource, compared between the
  document before and after the change. IAM policy parser that normalises the shorthand
  forms of the policy language.
- Rule R4: an ingress rule is newly open to `0.0.0.0/0` or `::/0`, for
  `aws_vpc_security_group_ingress_rule`, `aws_security_group_rule` and the inline
  ingress blocks of `aws_security_group`.
- Rule R5: a bucket or account public-access setting is turned off or its block
  destroyed, a public canned ACL is set, or a bucket policy newly allows anyone without
  a condition.
- `.plan-review.yml` configuration: ignore rules and override their severity; the
  report counts the ignored findings.
- `--format markdown` and `--format json` reports.
- Findings may quote IAM actions and resources, ports and CIDRs, but never a value the
  plan marks as sensitive.

- `plan-review` command: reads a `terraform show -json` output file, prints a plain-text
  report and exits 0, 1 (blocking finding) or 2 (unusable input or arguments).
- Typed model of the plan JSON (pydantic), with checks on `format_version` and on the
  action lists, and a helper for values known only after apply.
- Classification of each change: no-op, create, read, update, delete, forget, and
  replacement in both orders (delete then create, create then delete), including the
  forget-then-create and create-then-forget forms of a resource with
  `lifecycle { destroy = false }`.
- Rule R1: a stateful resource is destroyed. Rule R2: a stateful resource is replaced,
  with the reason Terraform gives, the attributes that forced it and, when the old object
  is only forgotten, a note that it is left running while the managed one starts empty.
- Explicit list of stateful AWS resource types used by R1 and R2.

- Project scaffold: `pyproject.toml` managed with uv, ruff, mypy in strict mode, pytest.
- Continuous integration: lint, type check, tests, and a job that verifies the sample
  plans match their Terraform sources.
- Six sample Terraform plans generated without an AWS account, with the script that
  regenerates them and a test that loads them.
- ADR-0001: the tool reviews the plan delta, not the state.
