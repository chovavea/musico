from __future__ import annotations

from pathlib import Path

from app.main import SPAStaticFiles
from starlette.applications import Starlette
from starlette.testclient import TestClient


def test_spa_static_files_fallbacks_client_routes_and_preserves_asset_404(
    tmp_path: Path,
) -> None:
    (tmp_path / "index.html").write_text("<div id='app'>musico</div>", encoding="utf-8")
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "app.js").write_text("console.log('ok')", encoding="utf-8")

    app = Starlette()
    app.mount("/", SPAStaticFiles(directory=str(tmp_path), html=True))
    client = TestClient(app)

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
