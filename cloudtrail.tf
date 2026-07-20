# ──────────────────────────────────────────────────────────────────────────────
# S3 bucket – CloudTrail log storage
# ──────────────────────────────────────────────────────────────────────────────

resource "aws_s3_bucket" "cloudtrail" {
  bucket        = "${local.project_name}-cloudtrail-${local.environment}-${data.aws_caller_identity.current.account_id}"
  force_destroy = true

  tags = merge(local.tags,
    {
      Name = "${local.project_name}-cloudtrail-${local.environment}"
      File = "cloudtrail.tf"
    }
  )
}

resource "aws_s3_bucket_lifecycle_configuration" "cloudtrail" {
  bucket = aws_s3_bucket.cloudtrail.id

  rule {
    id     = "expire-cloudtrail-logs"
    status = "Enabled"

    expiration {
      days = 365
    }
  }
}

resource "aws_s3_bucket_public_access_block" "cloudtrail" {
  bucket = aws_s3_bucket.cloudtrail.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_policy" "cloudtrail" {
  bucket = aws_s3_bucket.cloudtrail.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AWSCloudTrailAclCheck"
        Effect = "Allow"
        Principal = {
          Service = "cloudtrail.amazonaws.com"
        }
        Action   = "s3:GetBucketAcl"
        Resource = aws_s3_bucket.cloudtrail.arn
        Condition = {
          StringEquals = {
            "aws:SourceArn" = "arn:aws:cloudtrail:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:trail/${local.project_name}-cloudtrail-${local.environment}"
          }
        }
      },
      {
        Sid    = "AWSCloudTrailWrite"
        Effect = "Allow"
        Principal = {
          Service = "cloudtrail.amazonaws.com"
        }
        Action   = "s3:PutObject"
        Resource = "${aws_s3_bucket.cloudtrail.arn}/AWSLogs/${data.aws_caller_identity.current.account_id}/*"
        Condition = {
          StringEquals = {
            "s3:x-amz-acl"  = "bucket-owner-full-control"
            "aws:SourceArn" = "arn:aws:cloudtrail:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:trail/${local.project_name}-cloudtrail-${local.environment}"
          }
        }
      },
    ]
  })
}

# ──────────────────────────────────────────────────────────────────────────────
# CloudTrail – trail with read/write management events
# ──────────────────────────────────────────────────────────────────────────────

resource "aws_cloudtrail" "main" {
  name                          = "${local.project_name}-cloudtrail-${local.environment}"
  s3_bucket_name                = aws_s3_bucket.cloudtrail.id
  include_global_service_events = true
  is_multi_region_trail         = false
  enable_logging                = true

  event_selector {
    read_write_type           = "All"
    include_management_events = true
  }

  tags = merge(local.tags,
    {
      Name = "${local.project_name}-cloudtrail-${local.environment}"
      File = "cloudtrail.tf"
    }
  )

  depends_on = [aws_s3_bucket_policy.cloudtrail]
}
