import os
from pathlib import Path
from urllib.parse import quote

import requests


class CloudStorageError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def _config():
    return (
        os.getenv("SUPABASE_URL", "").rstrip("/"),
        os.getenv("SUPABASE_SERVICE_ROLE_KEY", ""),
        os.getenv("SUPABASE_STORAGE_BUCKET", "swaya-uploads"),
    )


def enabled() -> bool:
    url, key, bucket = _config()
    return bool(url and key and bucket)


def require_remote_storage() -> None:
    url, key, bucket = _config()
    if not (url and key and bucket):
        raise RuntimeError(
            "Production requires SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, "
            "and SUPABASE_STORAGE_BUCKET."
        )


def _headers(content_type: str | None = None):
    _, key, _ = _config()
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def _object_url(object_key: str) -> str:
    url, _, bucket = _config()
    encoded_key = quote(object_key.lstrip("/"), safe="/")
    return f"{url}/storage/v1/object/{quote(bucket, safe='')}/{encoded_key}"


def upload_file(local_path: str | Path, object_key: str, content_type: str) -> None:
    headers = _headers(content_type)
    headers["x-upsert"] = "true"
    try:
        with Path(local_path).open("rb") as source:
            response = requests.post(
                _object_url(object_key),
                headers=headers,
                data=source,
                timeout=(10, 300),
            )
        if not response.ok:
            raise CloudStorageError("Cloud upload failed", response.status_code)
    except requests.RequestException as exc:
        raise CloudStorageError("Cloud upload failed") from exc


def open_file(object_key: str):
    try:
        response = requests.get(
            _object_url(object_key),
            headers=_headers(),
            stream=True,
            timeout=(10, 300),
        )
        if not response.ok:
            status_code = response.status_code
            response.close()
            raise CloudStorageError("Cloud file unavailable", status_code)
        return response
    except requests.RequestException as exc:
        raise CloudStorageError("Cloud file unavailable") from exc


def delete_file(object_key: str) -> None:
    url, _, bucket = _config()
    endpoint = f"{url}/storage/v1/object/{quote(bucket, safe='')}"
    try:
        response = requests.delete(
            endpoint,
            headers=_headers("application/json"),
            json={"prefixes": [object_key.lstrip("/")]},
            timeout=(10, 60),
        )
        if not response.ok:
            raise CloudStorageError("Cloud delete failed", response.status_code)
    except requests.RequestException as exc:
        raise CloudStorageError("Cloud delete failed") from exc
