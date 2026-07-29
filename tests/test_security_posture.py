from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src/bunnyland"


def test_chroma_is_embedded_and_has_no_remote_code_surface() -> None:
    production = "\n".join(path.read_text() for path in SOURCE.rglob("*.py"))
    chroma = (SOURCE / "memory/chroma.py").read_text()

    assert "chromadb.PersistentClient(" in chroma
    assert "chromadb.EphemeralClient()" in chroma
    assert "chromadb.HttpClient(" not in production
    assert "chromadb.AsyncHttpClient(" not in production
    assert "trust_remote_code" not in production


def test_chroma_collection_selection_is_profile_scoped() -> None:
    handlers = (SOURCE / "memory/handlers.py").read_text()
    worldgen = (SOURCE / "worldgen/instantiate.py").read_text()

    assert (
        "MemoryProfileComponent(vector_collection=_memory_collection_name(spec.key))"
        in worldgen
    )
    assert "if collection not in profile.shared_collections:" in handlers
    assert 'raise ValueError("shared collection is not available")' in handlers


def test_container_bases_are_immutable_debian_images() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text().lower()

    assert "0.12.0-python3.14-trixie-slim@sha256:" in dockerfile
    assert "apt-get upgrade -y" in dockerfile
    assert "alpine" not in dockerfile
    assert "musl" not in dockerfile


def test_only_documented_chroma_advisory_is_ignored() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    grype = (ROOT / ".grype.yaml").read_text()
    scanner_exceptions = (ROOT / ".scanner-exceptions.yaml").read_text()
    exceptions = (ROOT / "docs/admin/security-exceptions.md").read_text()

    assert workflow.count("--ignore-vuln") == 1
    assert "--ignore-vuln PYSEC-2026-311" in workflow
    assert "anchore/scan-action@v7.4.0" in workflow
    assert "anchore/sbom-action@v0.24.0" in workflow
    assert "scripts/check-grype-findings bunnyland-server.grype.json" in workflow
    assert "only-fixed: false" in workflow
    assert "vulnerability: CVE-2026-45829" in grype
    assert "scanner: grype" in scanner_exceptions
    assert "`CVE-2026-45829` (`PYSEC-2026-311` in pip-audit)" in exceptions
