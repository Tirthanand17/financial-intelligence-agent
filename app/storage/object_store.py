from io import BytesIO

from minio import Minio

from app.core.config import get_settings


def get_minio_client() -> Minio:
    settings = get_settings()
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )


def ensure_bucket(client: Minio, bucket: str) -> None:
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)


def put_raw_document(*, source_id: str, sha256: str, content: bytes, content_type: str) -> str:
    settings = get_settings()
    client = get_minio_client()
    ensure_bucket(client, settings.minio_bucket)

    extension = {
        "application/pdf": "pdf",
        "text/html": "html",
        "text/plain": "txt",
    }.get(content_type.split(";", 1)[0].lower(), "bin")

    object_key = f"raw/{source_id}/{sha256}.{extension}"
    client.put_object(
        settings.minio_bucket,
        object_key,
        BytesIO(content),
        length=len(content),
        content_type=content_type,
    )
    return object_key
