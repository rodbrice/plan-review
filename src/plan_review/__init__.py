"""plan-review: review the risk of a Terraform plan before it is applied.

The tool reads the JSON produced by ``terraform show -json`` and reports changes that
deserve a second look before ``terraform apply``: stateful resources destroyed or
replaced, IAM policies widened, ingress opened to the world, buckets made public.

This package is at the scaffolding stage. Parsing, rules, reporters and the GitHub
Action land in later milestones; see the README and ``docs/adr/`` for the plan.
"""

__version__ = "0.1.0.dev0"

__all__ = ["__version__"]
