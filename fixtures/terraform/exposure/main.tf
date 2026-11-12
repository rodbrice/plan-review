# Scenario: network and storage exposure changes. Compared with seed.tfstate, the SSH
# rule opens from a private range to the whole IPv4 internet, a new SSH rule opens to
# the whole IPv6 internet, the HTTPS rule moves to a narrower private range, the
# assets bucket turns off all four public-access blocks, and the public-access block of
# the reports bucket is removed entirely. Both buckets themselves are unchanged.
#
# Expected plan: "update" for the SSH rule, the HTTPS rule and the assets block,
# "create" for the IPv6 rule, "delete" for the reports block, "no-op" for the buckets. A
# reviewer should flag the two world-open rules and the two buckets losing their
# protection, and leave the HTTPS rule alone.

resource "aws_vpc_security_group_ingress_rule" "ssh" {
  security_group_id = "sg-0123456789abcdef0"
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 22
  to_port           = 22
  ip_protocol       = "tcp"
}

resource "aws_vpc_security_group_ingress_rule" "ssh_ipv6" {
  security_group_id = "sg-0123456789abcdef0"
  cidr_ipv6         = "::/0"
  from_port         = 22
  to_port           = 22
  ip_protocol       = "tcp"
}

resource "aws_vpc_security_group_ingress_rule" "https_internal" {
  security_group_id = "sg-0123456789abcdef0"
  cidr_ipv4         = "10.1.0.0/16"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
}

resource "aws_s3_bucket" "assets" {
  bucket = "example-app-assets"
}

resource "aws_s3_bucket_public_access_block" "assets" {
  bucket = aws_s3_bucket.assets.id

  block_public_acls       = false
  block_public_policy     = false
  ignore_public_acls      = false
  restrict_public_buckets = false
}

resource "aws_s3_bucket" "reports" {
  bucket = "example-reports"
}
