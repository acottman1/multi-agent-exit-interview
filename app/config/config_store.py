"""
Config store — persistence layer for DomainConfig instances.

Configs are stored as JSON files in a designated directory (default:
app/config/instances/). The store supports save, load, list, and delete
with auto-increment naming to prevent silent overwrites.

Typical lifecycle:
  1. Meta-agent produces a DomainConfig + LLM-generated slug.
  2. save_domain_config(config, slug) writes it to the store.
  3. list_domain_configs() surfaces it in the instance picker.
  4. load_domain_config(slug) rehydrates it before an interview session.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.config.domain_config import DomainConfig

_DEFAULT_STORE_DIR = Path(__file__).parent / "instances"


# ── Summary object (lightweight, no full parse required) ──────────────────────

@dataclass
class ConfigSummary:
    slug: str
    display_name: str
    domain_name: str
    description: str
    file_path: Path


# ── Public API ────────────────────────────────────────────────────────────────

def save_domain_config(
    config: DomainConfig,
    slug: str | None = None,
    store_dir: Path = _DEFAULT_STORE_DIR,
) -> Path:
    """
    Persist a DomainConfig to the store directory as JSON.

    The slug defaults to config.domain_name. If a file with that slug
    already exists, auto-increments (_2, _3, ...) to prevent overwrites.
    Returns the path the file was written to.
    """
    store_dir.mkdir(parents=True, exist_ok=True)
    base = slug or config.domain_name
    path = _unique_path(store_dir, base)
    path.write_text(config.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_domain_config(
    slug: str,
    store_dir: Path = _DEFAULT_STORE_DIR,
) -> DomainConfig:
    """
    Load a DomainConfig by slug (filename without .json) from the store.

    Raises FileNotFoundError if the config does not exist.
    Raises ValueError if the JSON fails schema validation.
    """
    path = store_dir / f"{slug}.json"
    if not path.exists():
        raise FileNotFoundError(f"No config found for slug {slug!r} in {store_dir}")
    try:
        return DomainConfig.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except Exception as exc:
        raise ValueError(f"Config {slug!r} failed validation: {exc}") from exc


def list_domain_configs(
    store_dir: Path = _DEFAULT_STORE_DIR,
) -> list[ConfigSummary]:
    """
    Return a summary of every DomainConfig JSON in the store directory.

    Files that fail schema validation are silently skipped (partial saves,
    unrelated JSON, in-progress writes).
    """
    if not store_dir.exists():
        return []

    summaries: list[ConfigSummary] = []
    for path in sorted(store_dir.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            summaries.append(
                ConfigSummary(
                    slug=path.stem,
                    display_name=raw.get("display_name", path.stem),
                    domain_name=raw.get("domain_name", path.stem),
                    description=raw.get("description", ""),
                    file_path=path,
                )
            )
        except Exception:  # noqa: BLE001
            continue

    return summaries


def delete_domain_config(
    slug: str,
    store_dir: Path = _DEFAULT_STORE_DIR,
) -> None:
    """Delete a DomainConfig from the store by slug. Raises FileNotFoundError if absent."""
    path = store_dir / f"{slug}.json"
    if not path.exists():
        raise FileNotFoundError(f"No config found for slug {slug!r} in {store_dir}")
    path.unlink()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _unique_path(store_dir: Path, base: str) -> Path:
    """Return a non-conflicting path, auto-incrementing the suffix if needed."""
    candidate = store_dir / f"{base}.json"
    if not candidate.exists():
        return candidate
    counter = 2
    while True:
        candidate = store_dir / f"{base}_{counter}.json"
        if not candidate.exists():
            return candidate
        counter += 1
