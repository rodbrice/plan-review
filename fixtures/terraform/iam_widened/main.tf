# Scenario: IAM policy documents change. Compared with seed.tfstate, the orders reader
# goes from two read actions on one table to "dynamodb:*" on every resource, the
# deployer loses one action (it gets narrower, not wider), and a brand-new policy is
# created with "*" for both Action and Resource.
#
# Expected plan: "update" for the two existing policies, "create" for the new one. A
# reviewer comparing before and after should flag the reader as widened, leave the
# deployer alone, and decide how to treat a wildcard in a policy that did not exist.

resource "aws_iam_policy" "orders_reader" {
  name = "example-orders-reader"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["dynamodb:*"]
        Resource = "*"
      },
    ]
  })
}

resource "aws_iam_policy" "deployer" {
  name = "example-deployer"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:PutObject"]
        Resource = "arn:aws:s3:::example-app-assets/*"
      },
    ]
  })
}

resource "aws_iam_policy" "break_glass" {
  name = "example-break-glass"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "*"
        Resource = "*"
      },
    ]
  })
}
