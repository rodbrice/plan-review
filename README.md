# plan-review

Review the risk of a Terraform change before `terraform apply`.

`plan-review` reads the JSON that `terraform show -json` produces for a saved plan and
reports the changes that deserve a second look: a database or bucket about to be
destroyed or replaced, an IAM policy that just grew a wildcard, an ingress rule opened
to the whole internet, a bucket that loses its public-access block. It looks at the
delta between the current state and the planned state, not at the configuration in
isolation.

**Status: early development.** The command reads a plan and applies rules R1 and R2
(stateful resources destroyed or replaced) with plain-text output. Rules R3 to R5,
configuration and the other output formats are not written yet; the milestones below
describe what comes next.

## Usage

```sh
terraform plan -out=tfplan
terraform show -json tfplan > plan.json
plan-review plan.json          # or: terraform show -json tfplan | plan-review -
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

Exit status: 0 when no finding is blocking, 1 when at least one is (every R1 and R2
finding is), 2 when the input cannot be read or is not a Terraform plan in JSON format
1.x, or the arguments are wrong.

Findings never include attribute values, so sensitive values in the plan do not reach
the output. The resource types that count as stateful are listed explicitly in
[`src/plan_review/stateful.py`](src/plan_review/stateful.py); a type that is not listed
is not reported by R1 or R2.

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
| R3 | An IAM policy is widened | a new wildcard appears in `Action` or `Resource` | planned |
| R4 | Ingress is open to the world | a rule now allows `0.0.0.0/0` or `::/0` | planned |
| R5 | A bucket loses public-access protection | a public-access block is removed or relaxed | planned |

Each finding carries the rule ID, a severity, the resource address and a short
explanation of what changed. Text output exists today; Markdown and JSON are planned.

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
| C2 | Rules R3 to R5, `.plan-review.yml` configuration, Markdown and JSON output | planned |
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
src/plan_review/      the package: model, actions, stateful, rules, findings, report, cli
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
applique les règles R1 et R2 (ressource avec état détruite ou remplacée), avec une
sortie texte. Code de sortie : 0 sans constat bloquant, 1 avec au moins un constat
bloquant, 2 si l'entrée n'est pas un plan utilisable. Les règles R3 à R5, la
configuration et les autres formats de sortie restent à faire.

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
