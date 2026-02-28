"""S3 file storage — upload by project and cluster (category)."""
from __future__ import annotations

from app.config import settings


def s3_upload(
    file_content: bytes,
    s3_key: str,
    content_type: str,
) -> str:
    """
    Upload file to S3. Returns the S3 key (storage_path).
    Key format: {project_id}/{cluster}/{filename} for correct folder in file repo.
    """
    if not settings.s3_bucket:
        raise ValueError("S3 bucket not configured (set S3_BUCKET in .env)")

    import boto3

    client = boto3.client(
        "s3",
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id or None,
        aws_secret_access_key=settings.aws_secret_access_key or None,
    )
    client.put_object(
        Bucket=settings.s3_bucket,
        Key=s3_key,
        Body=file_content,
        ContentType=content_type,
    )
    return s3_key


def build_s3_key(project_id: str, cluster: str, filename: str) -> str:
    """Build S3 key so file repo shows file in correct folder: project_id/cluster/filename."""
    # Normalize cluster and filename (coerce to str in case of int from form/DB)
    cluster_str = str(cluster).strip() if cluster is not None else "Uncategorized"
    safe_cluster = cluster_str.replace(" ", "_")
    filename_str = str(filename) if filename is not None else "document"
    return f"{project_id}/{safe_cluster}/{filename_str}"


def s3_download(s3_key: str, content_type: str, expires_in: int = 3600) -> str:
    """
    Generate presigned GET URL for S3 object.
    Returns URL string for redirect/download.
    """
    if not settings.s3_bucket:
        raise ValueError("S3 bucket not configured (set S3_BUCKET in .env)")

    import boto3

    client = boto3.client(
        "s3",
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id or None,
        aws_secret_access_key=settings.aws_secret_access_key or None,
    )
    url = client.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.s3_bucket, "Key": s3_key, "ResponseContentType": content_type},
        ExpiresIn=expires_in,
    )
    return url
