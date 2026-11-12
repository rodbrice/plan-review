# Scenario: attributes that cannot be changed in place were edited, so Terraform plans
# to replace the resources. Compared with seed.tfstate: the database engine changed from
# postgres to mysql, the volume moved to another availability zone, the log bucket was
# renamed, and the ingress rule points at another security group.
#
# Expected plan: "delete" then "create" for the database and the volume (default
# order), "create" then "delete" for the bucket (create_before_destroy), and a
# replacement of the ingress rule, which holds no data. A reviewer should flag the three
# stateful replacements and treat the rule differently.

resource "aws_db_instance" "orders" {
  identifier                  = "example-orders"
  engine                      = "mysql"
  instance_class              = "db.t3.micro"
  allocated_storage           = 20
  username                    = "app"
  manage_master_user_password = true
  skip_final_snapshot         = true
}

resource "aws_ebs_volume" "data" {
  availability_zone = "eu-central-1b"
  size              = 40
}

resource "aws_s3_bucket" "logs" {
  bucket = "example-logs-v2"

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_vpc_security_group_ingress_rule" "https_internal" {
  security_group_id = "sg-0fedcba9876543210"
  cidr_ipv4         = "10.0.0.0/8"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
}
