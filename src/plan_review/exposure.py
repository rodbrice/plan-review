"""What rules R4 and R5 compare: ingress open to the internet and bucket public access.

Each function receives one resource change and returns short descriptions of what is
new in ``after`` compared with ``before``; an empty list means nothing to report.
Values that are known only after apply are missing from ``after`` and therefore never
count as open or public; such a change is not reported.

Resource types covered:

- R4: ``aws_vpc_security_group_ingress_rule`` (``cidr_ipv4`` and ``cidr_ipv6``),
  ``aws_security_group_rule`` with ``type = "ingress"`` and ``aws_security_group``
  (its inline ``ingress`` blocks; both use ``cidr_blocks`` and ``ipv6_cidr_blocks``).
- R5: ``aws_s3_bucket_public_access_block`` and ``aws_s3_account_public_access_block``
  (a setting turned off, or the block destroyed); ``aws_s3_bucket_acl`` and the
  ``acl`` argument of ``aws_s3_bucket`` (a canned ACL that grants access to everyone);
  ``aws_s3_bucket_policy`` (an ``Allow`` statement for ``Principal: "*"`` without a
  ``Condition``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from plan_review.actions import ChangeKind
from plan_review.iam import (
    Grant,
    PolicyError,
    Statement,
    allowed_grants,
    is_public_principal,
    parse_policy,
)
from plan_review.model import ResourceChange, attribute

WORLD_IPV4 = "0.0.0.0/0"
WORLD_IPV6 = "::/0"

# Protocol values that stand for every protocol and port.
ALL_PROTOCOLS = ("-1", "all")
# Protocol values whose ports are an ICMP type and code; -1 and -1 stand for all of them.
ICMP_PROTOCOLS = ("icmp", "icmpv6", "1", "58")

# Canned ACLs that grant access beyond the bucket owner's account, narrowest first:
# AllUsers includes AuthenticatedUsers.
PUBLIC_ACLS: dict[str, str] = {
    "authenticated-read": "any AWS account can list the bucket",
    "public-read": "anyone can list the bucket",
    "public-read-write": "anyone can list the bucket and write objects to it",
}

PUBLIC_ACCESS_BLOCK_TYPES = (
    "aws_s3_bucket_public_access_block",
    "aws_s3_account_public_access_block",
)
PUBLIC_ACCESS_SETTINGS = (
    "block_public_acls",
    "block_public_policy",
    "ignore_public_acls",
    "restrict_public_buckets",
)

# The attributes of each ingress type that R4 reads; if any is marked sensitive, the
# finding names the CIDR but not the ports.
_INGRESS_ATTRIBUTES: dict[str, tuple[str, ...]] = {
    "aws_vpc_security_group_ingress_rule": ("from_port", "to_port", "ip_protocol"),
    "aws_security_group_rule": ("from_port", "to_port", "protocol"),
    "aws_security_group": ("ingress",),
}


@dataclass(frozen=True, order=True)
class _Opening:
    cidr: str
    protocol: str
    from_port: int | None
    to_port: int | None

    def describe(self, *, ports: bool) -> str:
        if not ports:
            return self.cidr
        return f"{_ports(self.protocol, self.from_port, self.to_port)} from {self.cidr}"

    def covers(self, other: _Opening) -> bool:
        """Everything ``other`` lets in from its CIDR, this opening already let in."""
        if self.cidr != other.cidr:
            return False
        if self.protocol in ALL_PROTOCOLS:
            return True
        if self.protocol != other.protocol:
            return False
        if self.protocol in ICMP_PROTOCOLS:
            return _any_or_same(self.from_port, other.from_port) and _any_or_same(
                self.to_port, other.to_port
            )
        return _at_most(self.from_port, other.from_port) and _at_most(other.to_port, self.to_port)


def new_open_ingress(change: ResourceChange) -> list[str]:
    """R4: the ports newly reachable from the whole internet, described."""
    attributes = _INGRESS_ATTRIBUTES.get(change.type)
    if attributes is None:
        return []
    before = _openings(change.type, change.change.before)
    new = {
        opening
        for opening in _openings(change.type, change.change.after)
        if not any(old.covers(opening) for old in before)
    }
    show_ports = not any(change.change.is_sensitive([name]) for name in attributes)
    return [opening.describe(ports=show_ports) for opening in sorted(new)]


def removed_public_access_blocks(change: ResourceChange) -> list[str]:
    """R5: public-access settings that were on and are now off or gone."""
    if change.type not in PUBLIC_ACCESS_BLOCK_TYPES:
        return []
    scope = "account" if change.type == "aws_s3_account_public_access_block" else "bucket"
    before = change.change.before
    was_on = [name for name in PUBLIC_ACCESS_SETTINGS if attribute(before, name) is True]
    if not was_on:
        return []
    kind = change.change.kind
    if kind is ChangeKind.DELETE:
        return [
            f"Public access block removed; the {scope} no longer has {', '.join(was_on)} turned on."
        ]
    if kind is not ChangeKind.UPDATE and not kind.is_replacement:
        return []
    after = change.change.after
    turned_off = [
        name
        for name in was_on
        if attribute(after, name) is not True and not change.change.is_unknown_after([name])
    ]
    if not turned_off:
        return []
    return [f"Public access protection turned off for the {scope}: {', '.join(turned_off)}."]


def new_public_acl(change: ResourceChange) -> list[str]:
    """R5: a canned ACL that grants access to everyone, wider than the previous one."""
    if change.type not in ("aws_s3_bucket_acl", "aws_s3_bucket"):
        return []
    after = attribute(change.change.after, "acl")
    if not isinstance(after, str) or after not in PUBLIC_ACLS:
        return []
    before = attribute(change.change.before, "acl")
    if isinstance(before, str) and before in PUBLIC_ACLS and _acl_rank(before) >= _acl_rank(after):
        return []
    return [f"Bucket ACL set to {after}: {PUBLIC_ACLS[after]}."]


def new_public_bucket_statements(change: ResourceChange) -> list[str]:
    """R5: a bucket policy that newly allows anyone, without a condition."""
    if change.type != "aws_s3_bucket_policy":
        return []
    after = _public_grants(attribute(change.change.after, "policy"))
    new = after - _public_grants(attribute(change.change.before, "policy"))
    if not new:
        return []
    if change.change.is_sensitive(["policy"]):
        listed = f"{len(new)} action(s); the document is sensitive and not shown"
    else:
        listed = ", ".join(grant.describe() for grant in sorted(new))
    return [f"Bucket policy now allows anyone (Principal *) without a condition: {listed}."]


def _acl_rank(acl: str) -> int:
    return list(PUBLIC_ACLS).index(acl)


def _public_grants(text: object) -> set[Grant]:
    if not isinstance(text, str):
        return set()
    try:
        statements = parse_policy(text)
    except PolicyError:
        return set()
    return {
        grant
        for statement in statements
        if _is_public_allow(statement)
        for grant in allowed_grants(statement)
    }


def _is_public_allow(statement: Statement) -> bool:
    return statement.allows and is_public_principal(statement) and not statement.has_condition


def _openings(resource_type: str, values: object) -> set[_Opening]:
    if not isinstance(values, dict):
        return set()
    if resource_type == "aws_vpc_security_group_ingress_rule":
        cidrs = [values.get("cidr_ipv4"), values.get("cidr_ipv6")]
        return _open(cidrs, values.get("ip_protocol"), values)
    if resource_type == "aws_security_group_rule":
        if values.get("type") != "ingress":
            return set()
        return _open(_cidr_lists(values), values.get("protocol"), values)
    blocks = values.get("ingress")
    if not isinstance(blocks, list):
        return set()
    openings: set[_Opening] = set()
    for block in blocks:
        if isinstance(block, dict):
            openings |= _open(_cidr_lists(block), block.get("protocol"), block)
    return openings


def _cidr_lists(values: dict[str, Any]) -> list[object]:
    cidrs: list[object] = []
    for key in ("cidr_blocks", "ipv6_cidr_blocks"):
        listed = values.get(key)
        if isinstance(listed, list):
            cidrs.extend(listed)
    return cidrs


def _open(cidrs: list[object], protocol: object, values: dict[str, Any]) -> set[_Opening]:
    from_port = values.get("from_port")
    to_port = values.get("to_port")
    return {
        _Opening(
            cidr=cidr,
            protocol=str(protocol) if protocol is not None else "",
            from_port=from_port if isinstance(from_port, int) else None,
            to_port=to_port if isinstance(to_port, int) else None,
        )
        for cidr in cidrs
        if cidr in (WORLD_IPV4, WORLD_IPV6)
    }


def _any_or_same(before: int | None, after: int | None) -> bool:
    """An ICMP type or code already allowed: ``-1`` stands for any, else they must match."""
    return before == -1 or before == after


def _at_most(lower: int | None, upper: int | None) -> bool:
    """``lower <= upper`` where ``None`` is the open end of a range."""
    if lower is None:
        return True
    return upper is not None and lower <= upper


def _ports(protocol: str, from_port: int | None, to_port: int | None) -> str:
    if protocol in ALL_PROTOCOLS:
        return "all traffic"
    if protocol in ICMP_PROTOCOLS:
        return protocol
    if from_port is None or to_port is None:
        return protocol or "traffic"
    if from_port == to_port:
        return f"port {from_port}/{protocol}"
    return f"ports {from_port}-{to_port}/{protocol}"
