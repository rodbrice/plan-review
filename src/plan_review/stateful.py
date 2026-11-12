"""The resource types that hold data, which rules R1 and R2 protect.

This is an explicit list, not a heuristic: a type is stateful here because destroying
or replacing it loses something that Terraform cannot recreate from the configuration.
Each entry says what that is, and the text is used in the findings. Types that are not
listed are treated as stateless. Adding a type means adding one line and, ideally, a
test case.
"""

from __future__ import annotations

# Resource type -> what is lost when the object is destroyed or replaced.
STATEFUL_TYPES: dict[str, str] = {
    # Databases
    "aws_db_instance": "the databases on the instance",
    "aws_rds_cluster": "the cluster's databases",
    "aws_docdb_cluster": "the cluster's documents",
    "aws_neptune_cluster": "the cluster's graph data",
    "aws_redshift_cluster": "the warehouse data",
    "aws_dynamodb_table": "the items in the table",
    "aws_memorydb_cluster": "the data in the cluster",
    "aws_elasticache_replication_group": "the cached data in the replication group",
    "aws_elasticache_cluster": "the cached data in the cluster",
    "aws_opensearch_domain": "the indexes in the domain",
    "aws_elasticsearch_domain": "the indexes in the domain",
    # Storage
    "aws_s3_bucket": "the objects in the bucket",
    "aws_ebs_volume": "the data on the volume",
    "aws_efs_file_system": "the files in the file system",
    "aws_fsx_lustre_file_system": "the files in the file system",
    "aws_fsx_ontap_file_system": "the files in the file system",
    "aws_fsx_openzfs_file_system": "the files in the file system",
    "aws_fsx_windows_file_system": "the files in the file system",
    "aws_backup_vault": "the recovery points in the vault",
    "aws_glacier_vault": "the archives in the vault",
    "aws_ecr_repository": "the images in the repository",
    # Streams, queues and logs
    "aws_kinesis_stream": "the records in the stream",
    "aws_msk_cluster": "the topics and their messages",
    "aws_sqs_queue": "the messages in the queue",
    "aws_cloudwatch_log_group": "the log events in the group",
    # Secrets, keys and identities
    "aws_secretsmanager_secret": "the secret value and its versions",
    "aws_kms_key": "the key material; everything encrypted with the key becomes unreadable",
    "aws_cognito_user_pool": "the users in the pool",
}
