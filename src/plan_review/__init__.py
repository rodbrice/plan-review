"""plan-review: review the risk of a Terraform plan before it is applied.

The tool reads the JSON produced by ``terraform show -json`` and reports changes that
deserve a second look before ``terraform apply``: stateful resources destroyed or
replaced, IAM policies widened, ingress opened to the world, buckets made public.

Modules, in the order data flows through them:

- ``model``: the typed plan JSON and ``load_plan``;
- ``actions``: classification of each change (create, update, delete, replace, ...);
- ``stateful``: the explicit list of resource types that hold data;
- ``iam``: the IAM policy parser and the wildcard grants rule R3 compares;
- ``exposure``: what rules R4 and R5 compare (open ingress, bucket public access);
- ``rules``: the rules, pure functions from a resource change to findings;
- ``findings``: the ``Finding`` type and severities;
- ``config``: the optional ``.plan-review.yml`` file;
- ``report``: the text, Markdown and JSON reports;
- ``cli``: argument parsing and exit status.
"""

__version__ = "0.1.0.dev0"

__all__ = ["__version__"]
