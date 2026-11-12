# ADR-0001: Review the plan delta, not the state

- Status: Accepted
- Date: 2026-11-12

## Context

A Terraform change is applied from a plan. Before `terraform apply`, the plan is the
only artifact that says, for every resource, what exists now (`before`) and what will
exist afterwards (`after`), together with the action Terraform intends: create, update,
delete, or a replacement expressed as `["delete", "create"]` or `["create", "delete"]`.
`terraform show -json <planfile>` exposes all of this in a documented, versioned JSON
format.

Reviewing a long plan by eye is unreliable. The handful of lines that matter, such as a
database instance that "must be replaced" or a policy statement whose `Resource` became
`"*"`, sit among hundreds of harmless attribute changes.

Several mature tools already analyse Terraform. Checkov, Trivy, tfsec and similar
scanners check the configuration, or the state it will produce, against a catalogue of
misconfigurations: an unencrypted volume, a bucket without versioning, a security group
that allows SSH from anywhere. They answer "is the resulting infrastructure configured
badly?". They do not answer "what does this change destroy, replace or widen compared
with what is running today?", because that question needs the `before` side of the
plan.

## Decision

`plan-review` reads the JSON plan and reports on the delta between `before` and
`after`. Its rules are about transitions, not final values:

- a resource that holds data is destroyed or replaced (R1, R2);
- an IAM policy gains a wildcard it did not have (R3);
- an ingress rule opens to `0.0.0.0/0` or `::/0` (R4);
- a bucket loses the public-access protection it had (R5).

Consequences of this decision for the design:

- The input is `terraform show -json` output and nothing else. The tool does not run
  Terraform, does not read state files, and does not need cloud credentials.
- A plan with only `no-op` changes produces no findings, whatever the configuration
  looks like. A misconfiguration that already exists and is not touched by the plan is
  out of scope.
- The classification of actions comes from the plan itself (`change.actions`,
  `action_reason`); the tool does not infer it from attributes.
- "Stateful" is an explicit, small list of resource types that hold data, kept in the
  code and documented, not a heuristic.
- Rules are pure functions from a resource change to zero or more findings, so each one
  can be tested with one positive and one negative case taken from the sample plans.
- The sample plans are real Terraform output generated from minimal configurations
  without any cloud account, so the format the code parses is the format Terraform
  produces.

## What this tool is not

- Not a scanner for static misconfiguration. Existing tools do that well and this
  project does not duplicate them.
- Not a policy engine. There is no policy language and no promise to cover every risky
  pattern; the rule set is small and spelled out.
- Not a Terraform wrapper, a drift detector, or a cost estimator.
- Not provider-agnostic in its first version: the rules name AWS resource types.

## Alternatives considered

- **Analyse the configuration (HCL) directly.** Rejected: HCL has no `before`, so it
  cannot tell a creation from a replacement, and expressions are only resolved by
  Terraform at plan time.
- **Analyse the state file.** Rejected: state describes what exists, not what is about
  to change, and reading state means handling its secrets and its storage backend.
- **Write rules for an existing policy framework (OPA/Conftest, Sentinel).** Rejected
  for this project: it would make the result a rule pack rather than a tool, and the
  goal is a small, explainable Python program whose every module can be read and
  modified by its maintainer.
- **Use a large language model to summarise the plan.** Rejected as the mechanism of
  detection. Findings must be deterministic and reproducible. An optional, clearly
  labelled summary of already-detected findings may be considered later, and would
  never decide what is reported.
