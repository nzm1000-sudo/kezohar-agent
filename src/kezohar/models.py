"""Source record model."""
from dataclasses import dataclass, asdict, field
from typing import Dict, Any
import hashlib
import time

REQUIRED_FIELDS = ["source_id", "work_title", "reference", "text"]

@dataclass
class Source:
    source_id: str
    work_title: str
    author: str = ""
    reference: str = ""
    section: str = ""
    text: str = ""
    normalized_text: str = ""
    language: str = "he"
    tradition: str = ""
    license: str = ""
    source_url: str = ""
    version: str = ""
    ingested_at: str = ""

    def to_dict(self):
        return asdict(self)

    @staticmethod
    def from_dict(d):
        known = {f for f in Source.__dataclass_fields__}
        filt = {k: v for k, v in d.items() if k in known}
        return Source(**filt)  # type: ignore

def stable_id(work_title, reference, text):
    h = hashlib.sha256(f"{work_title}|{reference}|{text}".encode("utf-8")).hexdigest()[:16]
    return h

def utcnow_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
