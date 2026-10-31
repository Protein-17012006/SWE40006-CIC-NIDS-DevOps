"""The environment's S3 bucket and the layout of its folders (design section 5.1).

raw/ holds uploads and is never edited; processed/ holds cleaned Parquet; quarantine/ holds
the report and draft contract of each rejected file.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote_plus

import boto3
from botocore.exceptions import ClientError

from app.config import get_settings

_SUFFIX = ".csv"


@dataclass(frozen=True)
class RawFile:
    key: str
    dataset_id: str
    name: str

    @property
    def processed_prefix(self) -> str:
        return f"processed/{self.dataset_id}/{self.name}/"

    @property
    def report_key(self) -> str:
        return f"quarantine/{self.dataset_id}/{self.name}/report.md"

    @property
    def draft_key(self) -> str:
        return f"quarantine/{self.dataset_id}/{self.name}/draft-contract.yaml"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def parse_raw_key(key: str) -> RawFile | None:
    """The dataset is the first folder under raw/, or the file itself directly in raw/."""
    if not key.startswith("raw/") or not key.lower().endswith(_SUFFIX):
        return None
    path = key[len("raw/") : -len(_SUFFIX)]
    first, folder, rest = path.partition("/")
    name = rest if folder else first
    dataset_id = _slug(first)
    if not dataset_id or not name or name.endswith("/"):
        return None
    return RawFile(key=key, dataset_id=dataset_id, name=name)


class Bucket:
    def __init__(self, name: str, client=None) -> None:
        self.name = name
        self.client = client or boto3.client("s3", region_name=get_settings().aws_region)

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.name, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return False
            raise
        return True

    def resolve_key(self, key: str) -> str:
        """The key itself, else its URL-decoded form: event keys may encode spaces as + or %20."""
        if self.exists(key):
            return key
        decoded = unquote_plus(key)
        if decoded != key and self.exists(decoded):
            return decoded
        raise FileNotFoundError(f"s3://{self.name}/{key} does not exist")

    def download(self, key: str, path: Path) -> None:
        self.client.download_file(self.name, key, str(path))

    def upload(self, path: Path, key: str) -> None:
        self.client.upload_file(str(path), self.name, key)

    def put_text(self, key: str, text: str, content_type: str) -> None:
        self.client.put_object(
            Bucket=self.name, Key=key, Body=text.encode("utf-8"), ContentType=content_type
        )

    def read_text(self, key: str) -> str:
        body = self.client.get_object(Bucket=self.name, Key=key)["Body"]
        return body.read().decode("utf-8")

    def delete_prefix(self, prefix: str) -> int:
        deleted = 0
        pages = self.client.get_paginator("list_objects_v2").paginate(
            Bucket=self.name, Prefix=prefix
        )
        for page in pages:
            keys = [{"Key": item["Key"]} for item in page.get("Contents", [])]
            if keys:
                self.client.delete_objects(Bucket=self.name, Delete={"Objects": keys})
                deleted += len(keys)
        return deleted
