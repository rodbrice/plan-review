# Scenario: a fresh configuration with no prior state. Every resource is created and
# nothing in it is risky: the bucket blocks public access, the policy is scoped to one
# bucket, the ingress rule is limited to a private range.
#
# Expected plan: only "create" actions. A reviewer should report nothing blocking here.

resource "aws_s3_bucket" "assets" {
  bucket = "example-app-assets"
}

resource "aws_s3_bucket_public_access_block" "assets" {
  bucket = aws_s3_bucket.assets.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_iam_policy" "assets_reader" {
  name = "example-assets-reader"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:ListBucket"]
        Resource = ["arn:aws:s3:::example-app-assets", "arn:aws:s3:::example-app-assets/*"]
      },
    ]
  })
}

resource "aws_vpc_security_group_ingress_rule" "https_internal" {
  security_group_id = "sg-0123456789abcdef0"
  cidr_ipv4         = "10.0.0.0/8"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
}

resource "aws_db_instance" "orders" {
  identifier                  = "example-orders"
  engine                      = "postgres"
  instance_class              = "db.t3.micro"
  allocated_storage           = 20
  username                    = "app"
  manage_master_user_password = true
  skip_final_snapshot         = true
}
