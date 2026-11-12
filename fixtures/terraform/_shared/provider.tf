# Shared by every fixture scenario. scripts/generate_fixtures.py copies this file next to
# the scenario files before running Terraform.
#
# Nothing here talks to AWS. The credentials are placeholders, the provider skips every
# validation that would need the API, plans run with -refresh=false, and each service
# endpoint points at a closed local port so that an accidental call fails immediately
# instead of reaching the real service.

terraform {
  required_version = ">= 1.10, < 2.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "6.73.0"
    }
  }
}

provider "aws" {
  region     = "eu-central-1"
  access_key = "test"
  secret_key = "test"

  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_region_validation      = true
  skip_requesting_account_id  = true

  endpoints {
    ec2 = "http://127.0.0.1:1"
    efs = "http://127.0.0.1:1"
    iam = "http://127.0.0.1:1"
    rds = "http://127.0.0.1:1"
    s3  = "http://127.0.0.1:1"
    sts = "http://127.0.0.1:1"
  }
}
