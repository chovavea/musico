from __future__ import annotations

from pathlib import Path

from app.main import (
    ENTRY_CACHE_CONTROL,
    IMMUTABLE_ASSETS_CACHE_CONTROL,
    PUBLIC_FILE_CACHE_CONTROL,
    SPAStaticFiles,
)
from starlette.applications import Starlette
from starlette.testclient import TestClient


def build_client(root: Path) -> TestClient:
    """Stand up a `web/dist`-shaped tree: entry, hashed assets, unhashed public files."""
    (root / "index.html").write_text("<div id='app'>musico</div>", encoding="utf-8")
    (root / "manifest.webmanifest").write_text("{}", encoding="utf-8")
    (root / "favicon.svg").write_text("<svg />", encoding="utf-8")
    assets = root / "assets"
    assets.mkdir()
    (assets / "app.js").write_text("console.log('ok')", encoding="utf-8")

    app = Starlette()
    app.mount("/", SPAStaticFiles(directory=str(root), html=True))
    return TestClient(app)


def test_spa_static_files_fallbacks_client_routes_and_preserves_asset_404(
    tmp_path: Path,
) -> None:
    client = build_client(tmp_path)

    route = client.get("/boards")
    assert route.status_code == 200
    assert "musico" in route.text
    assert route.headers["content-type"].startswith("text/html")

    asset = client.get("/assets/app.js")
    assert asset.status_code == 200
    assert "console.log" in asset.text

    missing_asset = client.get("/assets/missing.js")
    assert missing_asset.status_code == 404

    missing_api = client.get("/api/v1/not-found")
    assert missing_api.status_code == 404


def test_spa_static_files_picks_cache_control_per_file(tmp_path: Path) -> None:
    client = build_client(tmp_path)

    for path in ("/", "/index.html", "/boards"):
        assert client.get(path).headers["cache-control"] == ENTRY_CACHE_CONTROL

    assert client.get("/assets/app.js").headers["cache-control"] == IMMUTABLE_ASSETS_CACHE_CONTROL
    assert client.get("/manifest.webmanifest").headers["cache-control"] == PUBLIC_FILE_CACHE_CONTROL
    assert client.get("/favicon.svg").headers["cache-control"] == PUBLIC_FILE_CACHE_CONTROL


def test_spa_static_files_keeps_cache_control_on_revalidation(tmp_path: Path) -> None:
    client = build_client(tmp_path)

    entry = client.get("/index.html")
    revalidated_entry = client.get("/index.html", headers={"if-none-match": entry.headers["etag"]})
    assert revalidated_entry.status_code == 304
    assert revalidated_entry.headers["cache-control"] == ENTRY_CACHE_CONTROL

    asset = client.get("/assets/app.js")
    revalidated_asset = client.get(
        "/assets/app.js", headers={"if-none-match": asset.headers["etag"]}
    )
    assert revalidated_asset.status_code == 304
    assert revalidated_asset.headers["cache-control"] == IMMUTABLE_ASSETS_CACHE_CONTROL
