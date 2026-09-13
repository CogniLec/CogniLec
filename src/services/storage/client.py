"""StorageClient - boto3-backed S3/MinIO wrapper with presigned URL support (S14)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any

import boto3
from botocore.client import Config
from botocore.exceptions import EndpointConnectionError
from src.core.config import Settings, get_settings
from src.services.storage.models import BucketName, ObjectMetadata, PresignedURLResponse

# Lifecycle rules per spec section 2. lis-uploads / lis-generated / lis-eval are
# permanent (no ILM); lis-eval is versioned via DVC and must never receive one.
AUDIO_ILM_EXPIRATION_DAYS = 30
EXPORTS_ILM_EXPIRATION_DAYS = 7
AUDIO_ILM_RULE_ID = "lis-audio-cleanup"
EXPORTS_ILM_RULE_ID = "lis-exports-cleanup"


class StorageClient:
    """Thin async wrapper around a boto3 S3 client pointed at MinIO."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        endpoint = self._settings.MINIO_ENDPOINT
        scheme = "https" if self._settings.MINIO_SECURE else "http"
        self._endpoint_url = f"{scheme}://{endpoint}"
        self._client = boto3.client(
            "s3",
            endpoint_url=self._endpoint_url,
            aws_access_key_id=self._settings.MINIO_ACCESS_KEY,
            aws_secret_access_key=self._settings.MINIO_SECRET_KEY,
            config=Config(signature_version="s3v4"),
            region_name="us-east-1",
        )

    def _bucket_name(self, bucket: BucketName) -> str:
        mapping = {
            BucketName.AUDIO: self._settings.MINIO_BUCKET_AUDIO,
            BucketName.UPLOADS: self._settings.MINIO_BUCKET_UPLOADS,
            BucketName.GENERATED: self._settings.MINIO_BUCKET_GENERATED,
            BucketName.EXPORTS: self._settings.MINIO_BUCKET_EXPORTS,
            BucketName.EVAL: self._settings.MINIO_BUCKET_EVAL,
        }
        return mapping[bucket]

    async def _run(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(None, partial(func, *args, **kwargs))
        except EndpointConnectionError as exc:
            msg = f"MinIO unreachable: {exc}"
            raise ConnectionError(msg) from exc

    async def generate_presigned_upload(
        self,
        bucket: BucketName,
        key: str,
        expires_in: int = 3600,
        content_type: str | None = None,
    ) -> PresignedURLResponse:
        """Generate a presigned PUT URL for direct client upload."""
        bucket_name = self._bucket_name(bucket)
        params: dict[str, str] = {"Bucket": bucket_name, "Key": key}
        if content_type:
            params["ContentType"] = content_type

        url = await self._run(
            self._client.generate_presigned_url,
            ClientMethod="put_object",
            Params=params,
            ExpiresIn=expires_in,
        )
        expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)
        return PresignedURLResponse(
            upload_url=url,
            key=key,
            bucket=bucket_name,
            expires_at=expires_at,
        )

    async def put_object(
        self,
        bucket: BucketName,
        key: str,
        data: bytes,
        content_type: str | None = None,
    ) -> ObjectMetadata:
        """Upload object directly (server-side)."""
        bucket_name = self._bucket_name(bucket)
        kwargs: dict[str, Any] = {"Bucket": bucket_name, "Key": key, "Body": data}
        if content_type:
            kwargs["ContentType"] = content_type
        response = await self._run(self._client.put_object, **kwargs)
        etag = str(response.get("ETag", "")).strip('"')
        return ObjectMetadata(
            bucket=bucket_name,
            key=key,
            size=len(data),
            etag=etag,
            last_modified=datetime.now(UTC),
        )

    async def get_object(self, bucket: BucketName, key: str) -> bytes:
        """Download object."""
        bucket_name = self._bucket_name(bucket)
        response = await self._run(self._client.get_object, Bucket=bucket_name, Key=key)
        body = response["Body"]
        data: bytes = await self._run(body.read)
        return data

    async def delete_object(self, bucket: BucketName, key: str) -> None:
        """Delete object."""
        bucket_name = self._bucket_name(bucket)
        await self._run(self._client.delete_object, Bucket=bucket_name, Key=key)

    async def list_objects(self, bucket: BucketName, prefix: str) -> list[ObjectMetadata]:
        """List objects under prefix."""
        bucket_name = self._bucket_name(bucket)
        response = await self._run(self._client.list_objects_v2, Bucket=bucket_name, Prefix=prefix)
        contents = response.get("Contents", [])
        return [
            ObjectMetadata(
                bucket=bucket_name,
                key=obj["Key"],
                size=obj["Size"],
                etag=str(obj["ETag"]).strip('"'),
                last_modified=obj["LastModified"],
            )
            for obj in contents
        ]

    def apply_lifecycle_policies(self) -> None:
        """Idempotently apply ILM rules to lis-audio (30d) and lis-exports (7d).

        lis-uploads, lis-generated, and lis-eval are permanent and must never
        receive a lifecycle rule (lis-eval is versioned via DVC).
        """
        self._client.put_bucket_lifecycle_configuration(
            Bucket=self._settings.MINIO_BUCKET_AUDIO,
            LifecycleConfiguration={
                "Rules": [
                    {
                        "ID": AUDIO_ILM_RULE_ID,
                        "Status": "Enabled",
                        "Filter": {"Prefix": ""},
                        "Expiration": {"Days": AUDIO_ILM_EXPIRATION_DAYS},
                    }
                ]
            },
        )
        self._client.put_bucket_lifecycle_configuration(
            Bucket=self._settings.MINIO_BUCKET_EXPORTS,
            LifecycleConfiguration={
                "Rules": [
                    {
                        "ID": EXPORTS_ILM_RULE_ID,
                        "Status": "Enabled",
                        "Filter": {"Prefix": ""},
                        "Expiration": {"Days": EXPORTS_ILM_EXPIRATION_DAYS},
                    }
                ]
            },
        )

    def get_lifecycle_rules(self, bucket: BucketName) -> list[dict[str, Any]]:
        """Return the lifecycle rules configured on a bucket, or [] if none."""
        bucket_name = self._bucket_name(bucket)
        try:
            response = self._client.get_bucket_lifecycle_configuration(Bucket=bucket_name)
        except self._client.exceptions.ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in ("NoSuchLifecycleConfiguration", "NoSuchLifecycleConfigurationError"):
                return []
            raise
        rules: list[dict[str, Any]] = response.get("Rules", [])
        return rules
