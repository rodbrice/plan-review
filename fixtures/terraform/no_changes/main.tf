# Scenario: the configuration matches the prior state exactly.
#
# Expected plan: only "no-op" actions. A reviewer must report nothing at all.

resource "aws_s3_bucket" "archive" {
  bucket = "example-archive"
}

resource "aws_s3_bucket_public_access_block" "archive" {
  bucket = aws_s3_bucket.archive.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_iam_policy" "archive_reader" {
  name = "example-archive-reader"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:ListBucket"]
        Resource = ["arn:aws:s3:::example-archive", "arn:aws:s3:::example-archive/*"]
      },
    ]
  })
}
