# plan-review

Review the risk of a Terraform change before `terraform apply`.

`plan-review` reads the JSON that `terraform show -json` produces for a saved plan and
reports the changes that deserve a second look: a database or bucket about to be
destroyed or replaced, an IAM policy that just grew a wildcard, an ingress rule opened
to the whole internet, a bucket that loses its public-access block. It looks at the
delta between the current state and the planned state, not at the configuration in
isolation.

**Status: early development.** The command reads a plan, applies rules R1 to R5 and
prints a text, Markdown or JSON report. A `.plan-review.yml` file can ignore a rule or
change its severity. The GitHub Action and the first release are the next milestone.

## Usage

```sh
terraform plan -out=tfplan
terraform show -json tfplan > plan.json
plan-review plan.json
```

From a checkout, run it as `uv run plan-review plan.json`. On the sample plan
`fixtures/plans/replace_stateful.json` the output starts with:

```
Plan: 4 to replace (Terraform 1.17.2)

R2 high   aws_db_instance.orders
    Replaced (delete, then create), because an attribute that cannot be updated in place
    changed. Forced by: engine. It holds the databases on the instance, and the new
    object starts empty.
```

Options:

- `--format text|markdown|json`: the report format (default `text`). Markdown suits a
  pull request comment; JSON has a `version` key, the change counts, and one object per
  finding with `rule`, `title`, `severity`, `blocking`, `address` and `message`.

The command reads `.plan-review.yml` from the current directory when that file exists.

Exit status: 0 when no finding is blocking, 1 when at least one is, 2 when the input
cannot be read or is not a Terraform plan in JSON format 1.x, the configuration file
cannot be used, or the arguments are wrong. A finding is blocking when its severity is
`high`.

Findings quote only what a reviewer needs to judge the change (an IAM action and
resource, a port and CIDR, a public-access setting name) and never a value Terraform
marks as sensitive. The resource types that count as stateful are listed explicitly in
[`src/plan_review/stateful.py`](src/plan_review/stateful.py); a type that is not listed
is not reported by R1 or R2.

## Configuration

```yaml
# .plan-review.yml
ignore:
  - R5          # drop every R5 finding
severity:
  R3: medium    # keep R3 findings in the report, but do not fail the command
```

Severities are `low`, `medium` and `high`; only `high` is blocking, so a severity
override decides whether a rule fails the command. An unknown key, rule ID or severity,
or a rule both ignored and given a severity, is an error (exit status 2). The report
says how many findings the configuration ignored.

## Why the delta

A long `terraform plan` buries the few lines that matter under hundreds of harmless
ones. Static scanners already check whether the final configuration is misconfigured.
The question they do not answer is what *this particular change* destroys, replaces or
widens compared with what is running today. That question needs the plan, because the
plan is the only artifact that carries both the `before` and the `after` of every
resource. See [ADR-0001](docs/adr/0001-review-the-plan-delta-not-the-state.md).

## Rules

| ID | Finding | Compared against | Status |
|----|---------|------------------|--------|
| R1 | A stateful resource is destroyed | the resource exists in the prior state | implemented |
| R2 | A stateful resource is replaced, in either order, even if the old object is only forgotten (`destroy = false`) | an attribute that forces replacement changed | implemented |
| R3 | An IAM policy is widened | an `Allow` statement grants an action and resource pair, with a wildcard on either side, that the previous document did not | implemented |
| R4 | Ingress is open to the world | a rule now allows `0.0.0.0/0` or `::/0` on a port that was not open to it before | implemented |
| R5 | A bucket is made public | a public-access block setting is turned off or the block is destroyed; a public canned ACL; a bucket policy statement for `Principal: "*"` without a condition | implemented |

Every finding is `high` severity. Each finding carries the rule ID, a severity, the
resource address and a short explanation of what changed.

Scope of R3 to R5, and what they do not do:

- R3 reads `aws_iam_policy`, `aws_iam_role_policy`, `aws_iam_user_policy` and
  `aws_iam_group_policy`. A wildcard is an action or a resource containing `*` or `?`
  anywhere (`s3:Get*`, `arn:aws:dynamodb:*:*:table/orders`,
  `arn:aws:iam::123456789012:role/*`, `arn:aws:s3:::bucket/*`), or
  `NotAction`/`NotResource` in an `Allow`. Conditions are not evaluated, a policy known
  only after apply or that cannot be parsed gives no finding, and policies attached by
  other means (inline `aws_iam_role` blocks, managed policy attachments) are not read.
- R4 reads `aws_vpc_security_group_ingress_rule`, `aws_security_group_rule` (ingress
  only) and the inline `ingress` blocks of `aws_security_group`. A rule narrowed from a
  wider world-open one (all traffic to one port, a port range to a single port) and a
  CIDR known only after apply are not reported.
- R5 reads `aws_s3_bucket_public_access_block`, `aws_s3_account_public_access_block`,
  `aws_s3_bucket_acl`, the `acl` argument of `aws_s3_bucket` and `aws_s3_bucket_policy`.
  Explicit ACL grants are not read. Destroying a public-access block is reported even
  when its bucket is destroyed in the same plan.

## What this is not

- Not a replacement for Checkov, Trivy, tfsec or similar scanners. They examine the
  configuration or the resulting state for misconfiguration; this tool only looks at
  what a single plan changes.
- Not a policy engine. There is no policy language, no custom rule DSL, and no claim to
  cover every risky pattern. The rule set is small and explicit on purpose.
- Not a cost estimator, a drift detector or a Terraform wrapper. It never runs
  Terraform, never reads state files directly, and never needs cloud credentials.
- Not multi-cloud yet. The first rules target AWS resource types.

## Milestones

| Milestone | Content | Status |
|-----------|---------|--------|
| C0 | Project scaffold, CI, sample plans, scope decision | done |
| C1 | Plan loader, change classification, rules R1 and R2, text output, exit codes | done |
| C2 | Rules R3 to R5, `.plan-review.yml` configuration, Markdown and JSON output | done |
| C3 | Composite GitHub Action that comments on pull requests, release v0.1 | planned |

## Development

Requirements: Python 3.12 or newer and [uv](https://docs.astral.sh/uv/).

```sh
uv sync                     # create .venv and install the development tools
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
```

CI runs the same four checks on Python 3.12 and 3.13 for every pull request, plus a job
that regenerates the sample plans and fails if the committed files differ from their
Terraform sources.

### Sample plans

`fixtures/plans/*.json` are real `terraform show -json` outputs produced from the
minimal configurations in `fixtures/terraform/`, without any AWS account. The provider
is given placeholder credentials, skips every check that would need the API, runs with
`-refresh=false`, and points each service endpoint at a closed local port. Scenarios
that need prior state (a destroy, a replacement, an update) ship a small `seed.tfstate`.
[fixtures/README.md](fixtures/README.md) explains each scenario and how to regenerate
the files:

```sh
uv run scripts/generate_fixtures.py          # requires terraform 1.17.2 on PATH
uv run scripts/generate_fixtures.py --check  # what CI runs
```

Everything in the fixtures is synthetic: the account ID is `123456789012`, resource IDs
are placeholders, and no credential is real.

## Project layout

```
src/plan_review/      the package: model, actions, stateful, iam, exposure, rules, findings,
                      config, report, cli
tests/                pytest suite
fixtures/terraform/   one directory per scenario: main.tf and, when needed, seed.tfstate
fixtures/plans/       the generated plan JSON files used by the tests
scripts/              generate_fixtures.py
docs/adr/             architecture decision records
docs/validation/      commands run and results observed for each milestone
.github/workflows/    CI
```

## License

[MIT](LICENSE).

---

## Résumé (français)

`plan-review` lit le JSON produit par `terraform show -json` pour un plan enregistré et
signale les changements qui méritent un second regard avant `terraform apply` : une base
de données ou un bucket détruit ou remplacé, une politique IAM qui s'élargit à un
joker, une règle d'entrée ouverte à tout Internet, un bucket qui perd son blocage
d'accès public. L'outil examine le delta entre l'état actuel et l'état planifié, et non
la configuration seule.

**État : développement initial.** La commande `plan-review plan.json` lit un plan et
applique les règles R1 à R5 : ressource avec état détruite (R1) ou remplacée (R2),
politique IAM élargie (R3), règle d'entrée ouverte à tout Internet (R4), bucket rendu
public (R5). Le rapport est en texte, Markdown ou JSON (`--format`). Un fichier
`.plan-review.yml` peut ignorer une règle ou changer sa sévérité. Code de sortie : 0
sans constat bloquant, 1 avec au moins un constat bloquant, 2 si l'entrée ou la
configuration n'est pas utilisable. L'action GitHub et la première version publiée
restent à faire.

**Ce que l'outil n'est pas :** ni un remplaçant de Checkov, Trivy ou tfsec, qui
analysent la configuration finale ; ni un moteur de politiques ; ni un estimateur de
coûts ; ni une surcouche de Terraform. Il n'exécute jamais Terraform et n'a besoin
d'aucun identifiant cloud.

**Développement :** Python 3.12 ou plus récent, et uv. `uv sync`, puis `uv run ruff check .`,
`uv run mypy` et `uv run pytest`. Les plans d'exemple sont de vraies sorties de
Terraform générées sans compte AWS (identifiants factices, validations désactivées,
points de terminaison pointés vers un port local fermé) ; `fixtures/README.md` décrit
chaque scénario et `scripts/generate_fixtures.py` les régénère.

Licence MIT.
