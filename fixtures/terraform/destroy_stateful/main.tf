# Scenario: resources were removed from the configuration while they still exist in
# the prior state (seed.tfstate). Terraform plans to destroy them.
#
# Expected plan: "delete" for a database instance, a bucket and a file system (all of
# them hold data) and for an IAM policy (which holds none); "no-op" for the ingress rule
# that stays. A reviewer should flag the three stateful destructions.

resource "aws_vpc_security_group_ingress_rule" "https_internal" {
  security_group_id = "sg-0123456789abcdef0"
  cidr_ipv4         = "10.0.0.0/8"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
}
