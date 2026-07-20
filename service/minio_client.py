import json
from datetime import timedelta
from io import BytesIO
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlparse

from minio import Minio
from minio.error import S3Error

from service.config import Settings, get_settings


class MinioObjectNotFoundError(Exception):
    """Raised when a referenced MinIO object does not exist."""


class MinioStorage:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.client = Minio(
            self.settings.minio_endpoint,
            access_key=self.settings.minio_access_key,
            secret_key=self.settings.minio_secret_key,
            secure=self.settings.minio_secure,
            region="us-east-1",
        )
        # Signs URLs for the host-reachable endpoint without contacting it
        # (region avoids GetBucketLocation against localhost from inside Docker)
        self.public_client = Minio(
            self.settings.minio_public_endpoint,
            access_key=self.settings.minio_access_key,
            secret_key=self.settings.minio_secret_key,
            secure=self.settings.minio_secure,
            region="us-east-1",
        )
        self.bucket = self.settings.minio_bucket

    def ensure_bucket(self) -> None:
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)

    def upload_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        self.client.put_object(
            self.bucket,
            key,
            BytesIO(data),
            length=len(data),
            content_type=content_type,
        )
        return key

    def upload_text(self, key: str, text: str, content_type: str = "text/plain; charset=utf-8") -> str:
        return self.upload_bytes(key, text.encode("utf-8"), content_type=content_type)

    def upload_json(self, key: str, payload: dict | list) -> str:
        data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        return self.upload_bytes(key, data, content_type="application/json")

    def upload_file(self, key: str, local_path: Path) -> str:
        self.client.fput_object(self.bucket, key, str(local_path))
        return key

    def upload_directory(self, prefix: str, local_dir: Path) -> list[str]:
        uploaded: list[str] = []
        if not local_dir.exists():
            return uploaded

        prefix = prefix.rstrip("/")
        for path in local_dir.rglob("*"):
            if path.is_file():
                relative = path.relative_to(local_dir).as_posix()
                key = f"{prefix}/{relative}" if relative else prefix
                self.upload_file(key, path)
                uploaded.append(key)
        return uploaded

    def presigned_get_url(self, key: str, expires_hours: int | None = None) -> str:
        hours = expires_hours if expires_hours is not None else self.settings.minio_presign_expiry_hours
        return self.public_client.presigned_get_object(
            self.bucket,
            key,
            expires=timedelta(hours=hours),
        )

    def list_objects(self, prefix: str) -> list[dict]:
        prefix = prefix.rstrip("/") + "/"
        artifacts: list[dict] = []
        try:
            for obj in self.client.list_objects(self.bucket, prefix=prefix, recursive=True):
                key = obj.object_name
                artifacts.append(
                    {
                        "key": key,
                        "size": obj.size,
                        "last_modified": obj.last_modified.isoformat() if obj.last_modified else None,
                        "download_url": self.presigned_get_url(key),
                    }
                )
        except S3Error:
            return []
        return artifacts

    def job_prefix(self, job_id: str) -> str:
        return f"jobs/{job_id}"

    def parse_object_ref(self, ref: str, *, default_bucket: str | None = None) -> tuple[str, str]:
        """Resolve bucket/key from object key, s3:// URL, or http(s) MinIO URL."""
        cleaned = ref.strip()
        bucket = default_bucket or self.bucket

        if cleaned.startswith("s3://"):
            without_scheme = cleaned[5:]
            parts = without_scheme.split("/", 1)
            if len(parts) != 2 or not parts[0] or not parts[1]:
                raise ValueError(f"Referencia s3:// inválida: {ref}")
            return parts[0], parts[1].lstrip("/")

        if cleaned.startswith("http://") or cleaned.startswith("https://"):
            parsed = urlparse(cleaned)
            path = unquote(parsed.path.lstrip("/"))
            if not path:
                raise ValueError(f"URL MinIO sin ruta de objeto: {ref}")
            parts = path.split("/", 1)
            if len(parts) == 2 and parts[0] and parts[1]:
                return parts[0], parts[1]
            return bucket, path

        return bucket, cleaned.lstrip("/")

    def object_exists(self, bucket: str, key: str) -> bool:
        try:
            self.client.stat_object(bucket, key)
            return True
        except S3Error:
            return False

    def download_object(self, ref: str, destination: Path, *, default_bucket: str | None = None) -> Path:
        bucket, key = self.parse_object_ref(ref, default_bucket=default_bucket)
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.client.fget_object(bucket, key, str(destination))
        except S3Error as exc:
            raise MinioObjectNotFoundError(f"No se pudo descargar '{ref}' ({bucket}/{key}): {exc}") from exc
        return destination

    def download_object_text(self, ref: str, *, default_bucket: str | None = None) -> str:
        bucket, key = self.parse_object_ref(ref, default_bucket=default_bucket)
        try:
            response = self.client.get_object(bucket, key)
        except S3Error as exc:
            raise MinioObjectNotFoundError(f"No se pudo leer '{ref}' ({bucket}/{key}): {exc}") from exc
        try:
            return response.read().decode("utf-8")
        finally:
            response.close()
            response.release_conn()

    def try_download_object(self, ref: str, destination: Path, *, default_bucket: str | None = None) -> bool:
        try:
            self.download_object(ref, destination, default_bucket=default_bucket)
            return True
        except MinioObjectNotFoundError:
            return False

    @staticmethod
    def local_name_from_ref(ref: str, fallback: str) -> str:
        cleaned = ref.strip()
        if cleaned.startswith("s3://"):
            without_scheme = cleaned[5:]
            key = without_scheme.split("/", 1)[1] if "/" in without_scheme else without_scheme
        elif cleaned.startswith("http://") or cleaned.startswith("https://"):
            parsed = urlparse(cleaned)
            path = unquote(parsed.path.lstrip("/"))
            parts = path.split("/", 1)
            key = parts[1] if len(parts) == 2 else path
        else:
            key = cleaned.lstrip("/")
        name = PurePosixPath(key).name
        return name or fallback
