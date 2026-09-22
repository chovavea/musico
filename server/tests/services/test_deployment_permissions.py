from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("compose_path", ["compose.yaml", "deploy/compose.yaml"])
def test_library_mount_is_initialized_before_the_non_root_application(compose_path: str) -> None:
    services = yaml.safe_load((ROOT / compose_path).read_text(encoding="utf-8"))["services"]
    init = services["music-init"]
    app = services["musico"]
    assert init["image"] == app["image"]
    assert init["user"] == "0:0"
    assert init["entrypoint"] == ["sh", "-c"]
    assert init["command"] == [
        "chown 1000:1000 /app/data/music && chmod u+rwx /app/data/music"
    ]
    assert init["volumes"] == ["./data/music:/app/data/music"]
    assert init["volumes"][0] in app["volumes"]
    assert init["network_mode"] == "none"
    assert init["read_only"] is True
    assert init["restart"] == "no"
    assert "env_file" not in init and "environment" not in init
    assert app["depends_on"]["music-init"]["condition"] == "service_completed_successfully"
    assert "user" not in app
    assert "USER appuser" in (ROOT / "Dockerfile").read_text(encoding="utf-8")
