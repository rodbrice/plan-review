# Sample plans

`plans/*.json` are the test fixtures: real outputs of `terraform show -json`, generated
by `scripts/generate_fixtures.py` from the scenarios under `terraform/`. The tests load
every file and check that each scenario contains the change shapes it documents.

## How they are generated without an AWS account

Terraform needs the AWS provider to plan, but the provider only calls the API to
validate credentials, to read the account ID and to refresh existing resources. The
shared configuration in `terraform/_shared/provider.tf` turns all of that off:

- placeholder credentials (`test` / `test`) and the four `skip_*` settings;
- `terraform plan -refresh=false`, so prior state is taken as is;
- every service endpoint set to `http://127.0.0.1:1`, a closed local port, so an
  unexpected call fails immediately instead of reaching AWS.

Creating a resource needs no prior state. Destroying, replacing or updating one does,
and prior state cannot be obtained without applying. Those scenarios therefore ship a
small hand-written `seed.tfstate` with the minimum attributes the provider schema
expects; the generator copies it into the working directory as `terraform.tfstate`. The
plan JSON itself is produced entirely by Terraform.

Some resource types validate their changes against the API while planning (for example
`aws_dynamodb_table` calls `DescribeTable`). Such types cannot be used in these
scenarios; the ones below plan fully offline with provider 6.73.0.

Everything is synthetic: account ID `123456789012`, placeholder resource IDs, bucket
names starting with `example-`, no real credential anywhere.

## Scenarios

| Scenario | Prior state | Actions in the plan | Exercises |
|----------|-------------|---------------------|-----------|
| `create_baseline` | none | create | a safe plan: nothing destroyed, policy scoped, ingress private, bucket blocked |
| `no_changes` | matches the configuration | no-op | a plan that must produce no finding at all |
| `destroy_stateful` | database, bucket, file system, policy, ingress rule | delete, no-op | R1: three stateful destructions plus one stateless (the policy) |
| `replace_stateful` | database, volume, bucket, ingress rule | delete+create, create+delete | R2: both replacement orderings, plus a stateless replacement |
| `iam_widened` | two policies | update, create | R3: one policy widened, one narrowed, one new with `*` |
| `exposure` | two ingress rules, two buckets with public-access blocks | update, create, delete, no-op | R4 and R5: rules opened to `0.0.0.0/0` and `::/0`, one rule narrowed, one block relaxed, one block removed |

Each `main.tf` starts with a comment that spells out what changed against the seed and
what a reviewer should conclude.

## Regenerating

```sh
uv run scripts/generate_fixtures.py            # rewrite plans/*.json
uv run scripts/generate_fixtures.py --check    # exit 1 if any committed plan is stale
```

The script requires Terraform 1.17.2 on `PATH`, because the Terraform version is
recorded inside every plan; the provider version is pinned in
`terraform/_shared/provider.tf` and verified by the lock file next to it. The provider
is downloaded once per run into `TF_PLUGIN_CACHE_DIR` when that variable is set, or into
a temporary cache otherwise; setting the variable makes later runs faster. The only
normalisation applied to Terraform's output is the removal of the top-level
`timestamp`; the rest is written as returned, pretty-printed.

The `fixtures` job in CI runs `--check`, so a scenario and its plan cannot drift apart.
