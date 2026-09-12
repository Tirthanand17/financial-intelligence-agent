from functools import lru_cache

import boto3
from botocore.client import BaseClient
from botocore.exceptions import ClientError

from app.core.config import get_settings


@lru_cache
def get_s3_client() -> BaseClient:
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key,
        region_name=settings.s3_region,
    )


def ensure_bucket(client: BaseClient, bucket: str) -> None:
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as exc:
        raise RuntimeError(
            f"Object-storage bucket '{bucket}' is unavailable. Create it first and check the S3 credentials."
        ) from exc


def put_raw_document(*, source_id: str, sha256: str, content: bytes, content_type: str) -> str:
    settings = get_settings()
    client = get_s3_client()
    ensure_bucket(client, settings.s3_bucket)

    extension = {
        "application/pdf": "pdf",
        "text/html": "html",
        "text/plain": "txt",
    }.get(content_type.split(";", 1)[0].lower(), "bin")

    object_key = f"raw/{source_id}/{sha256}.{extension}"
    client.put_object(
        Bucket=settings.s3_bucket,
        Key=object_key,
        Body=content,
        ContentType=content_type,
    )
    return object_key


def delete_raw_document(object_key: str) -> None:
    settings = get_settings()
    client = get_s3_client()
    ensure_bucket(client, settings.s3_bucket)
    client.delete_object(Bucket=settings.s3_bucket, Key=object_key)
