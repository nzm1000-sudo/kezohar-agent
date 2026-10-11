"""Modular source ingestion: import, license check, dedup, normalize, chunk, resume."""
import json
from pathlib import Path
from . import hebrew
from .models import Source, stable_id, utcnow_iso

CHUNK_MAX_CHARS = 1500

def load_licenses(path=None):
    p = Path(path) if path else Path.cwd() / "data" / "licenses.json"
    if not p.exists():
        # try repo root relative to this file
        p = Path(__file__).resolve().parent.parent.parent / "data" / "licenses.json"
    return json.loads(p.read_text(encoding="utf-8"))

def license_allows(licenses, license_id):
    entry = licenses.get(license_id)
    if not entry:
        return False
    return bool(entry.get("allows_full_text"))

def chunk_text(text, max_chars=CHUNK_MAX_CHARS):
    """Split long text into chunks on sentence boundaries (Hebrew-safe)."""
    if not text or len(text) <= max_chars:
        return [text] if text else []
    chunks, cur = [], ""
    # split on . : ; ׃ ؟ | newline — keep it simple
    import re
    parts = re.split(r'(?<=[.:;׃\n])\s+', text)
    for part in parts:
        if len(cur) + len(part) + 1 <= max_chars:
            cur = (cur + " " + part).strip()
        else:
            if cur:
                chunks.append(cur)
            if len(part) > max_chars:
                # hard split long part
                for i in range(0, len(part), max_chars):
                    chunks.append(part[i:i+max_chars])
                cur = ""
            else:
                cur = part
    if cur:
        chunks.append(cur)
    return chunks or [text]

def prepare_source(raw, licenses):
    """Validate + normalize a raw dict. Returns (sources, error)."""
    lic = raw.get("license", "")
    if not lic or not license_allows(licenses, lic):
        return [], f"license not allowed: {lic!r} for {raw.get('work_title')}/{raw.get('reference')}"
    text = (raw.get("text") or "").strip()
    if not text:
        return [], f"empty text for {raw.get('work_title')}/{raw.get('reference')}"
    work = raw.get("work_title", "")
    ref = raw.get("reference", "")
    chunks = chunk_text(text)
    out = []
    for i, ch in enumerate(chunks):
        section = raw.get("section", "") or (f"part{i+1}" if len(chunks) > 1 else "")
        sid = raw.get("source_id") or stable_id(work, f"{ref}#{section}" if section else ref, ch)
        out.append(Source(
            source_id=sid,
            work_title=work,
            author=raw.get("author", ""),
            reference=ref,
            section=section,
            text=ch,
            normalized_text=hebrew.normalize(ch),
            language=raw.get("language", "he"),
            tradition=raw.get("tradition", ""),
            license=lic,
            source_url=raw.get("source_url", ""),
            version=raw.get("version", ""),
            ingested_at=utcnow_iso(),
            book_id=raw.get("book_id", ""),
            book_title=raw.get("book_title", ""),
            category=raw.get("category", ""),
            source_project=raw.get("source_project", ""),
            source_file=raw.get("source_file", ""),
            authority_level=raw.get("authority_level", ""),
            reference_en=raw.get("reference_en", ""),
            verification_status=raw.get("verification_status", ""),
            provenance=raw.get("provenance", ""),
        ))
    return out, ""

def ingest_sources(raw_list, store_path, licenses=None, progress_path=None, errors_path=None):
    """Ingest list of raw dicts into JSONL store. Resumable via progress file.
    Returns dict with counts."""
    licenses = licenses or load_licenses()
    store = Path(store_path)
    store.parent.mkdir(parents=True, exist_ok=True)
    seen = set()
    if store.exists():
        for line in store.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    seen.add(json.loads(line)["source_id"])
                except Exception:
                    pass
    done_idx = -1
    if progress_path and Path(progress_path).exists():
        try:
            done_idx = int(json.loads(Path(progress_path).read_text(encoding="utf-8")).get("done_idx", -1))
        except Exception:
            done_idx = -1
    errors = []
    added, skipped_dup, skipped_err = 0, 0, 0
    with store.open("a", encoding="utf-8") as f:
        for idx, raw in enumerate(raw_list):
            if idx <= done_idx:
                continue
            try:
                sources, err = prepare_source(raw, licenses)
                if err:
                    errors.append({"idx": idx, "error": err})
                    skipped_err += 1
                else:
                    for s in sources:
                        if s.source_id in seen:
                            skipped_dup += 1
                            continue
                        f.write(json.dumps(s.to_dict(), ensure_ascii=False) + "\n")
                        seen.add(s.source_id)
                        added += 1
            except Exception as e:
                errors.append({"idx": idx, "error": str(e)})
                skipped_err += 1
            if progress_path:
                Path(progress_path).parent.mkdir(parents=True, exist_ok=True)
                Path(progress_path).write_text(json.dumps({"done_idx": idx}, ensure_ascii=False), encoding="utf-8")
    if errors_path and errors:
        Path(errors_path).parent.mkdir(parents=True, exist_ok=True)
        Path(errors_path).write_text(json.dumps(errors, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"added": added, "skipped_dup": skipped_dup, "skipped_err": skipped_err, "errors": errors}

def load_store(store_path):
    """Load JSONL store into list of Source."""
    p = Path(store_path)
    out = []
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(Source.from_dict(json.loads(line)))
    return out
