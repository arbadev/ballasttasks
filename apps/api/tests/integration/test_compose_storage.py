"""What ``docker compose`` really tells the API container about attachment storage.

The compose file is a machine-consumed artifact, so it is rendered through its own
consumer (``docker compose config``) and the resolved model is asserted, never the text.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

DOCKER = shutil.which("docker")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(DOCKER is None, reason="needs the docker CLI"),
]

REPO_ROOT = Path(__file__).resolve().parents[4]
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
# Everything the file demands loudly; the storage directory is what each case varies.
REQUIRED_ENV = """POSTGRES_USER=ballast
POSTGRES_PASSWORD=ballast
POSTGRES_DB=ballasttasks
NEXT_PUBLIC_API_URL=http://localhost:8000
"""
VOLUME_DEFAULT = "/var/lib/ballasttasks/attachments"


def _rendered(project: Path, dotenv: str) -> dict[str, Any]:
    """The model docker would act on for a project whose ``.env`` is ``dotenv``."""
    project.mkdir()
    shutil.copy(COMPOSE_FILE, project / "docker-compose.yml")
    (project / ".env").write_text(dotenv)
    result = subprocess.run(  # noqa: S603  (argv of constants, no shell)
        [
            str(DOCKER),
            "compose",
            "--project-directory",
            str(project),
            "-f",
            str(project / "docker-compose.yml"),
            "config",
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        check=True,
        # Nothing inherited: only what the .env above says.
        env={"PATH": os.environ["PATH"], "HOME": os.environ["HOME"]},
    )
    return dict(json.loads(result.stdout))


@pytest.mark.parametrize(
    ("dotenv", "target"),
    [
        pytest.param("", VOLUME_DEFAULT, id="a .env from before attachments"),
        pytest.param("STORAGE__LOCAL_DIRECTORY=\n", VOLUME_DEFAULT, id="left empty"),
        pytest.param("STORAGE__LOCAL_DIRECTORY=/srv/files\n", "/srv/files", id="set explicitly"),
    ],
)
def test_the_api_writes_where_the_attachments_volume_is_mounted(
    tmp_path: Path, dotenv: str, target: str
) -> None:
    """Whatever ``.env`` says, the API is told the same path the named volume is mounted
    at: it must not fall back to its own relative default, which the volume is not on and
    the image's non-root user cannot create.

    Alignment is all this proves, and all the variable does. A path other than the default
    is writable only once ``apps/api/Dockerfile`` creates and owns it too; see ADR 0008.
    """
    api = _rendered(tmp_path / "project", REQUIRED_ENV + dotenv)["services"]["api"]

    mounted = [volume for volume in api["volumes"] if volume["source"] == "attachments-data"]

    assert [volume["target"] for volume in mounted] == [target]
    assert api["environment"]["STORAGE__LOCAL_DIRECTORY"] == target


def test_project_name_isolates_both_application_images(tmp_path: Path) -> None:
    model = _rendered(
        tmp_path / "project", REQUIRED_ENV + "COMPOSE_PROJECT_NAME=packaging-contract\n"
    )
    services = model["services"]
    assert model["name"] == "packaging-contract"
    assert services["api"]["image"] == "packaging-contract-api"
    assert services["worker"]["image"] == services["api"]["image"]
    assert services["web"]["image"] == "packaging-contract-web"


@pytest.mark.parametrize("custom_ports", [False, True])
def test_only_http_ports_are_published_on_loopback(tmp_path: Path, custom_ports: bool) -> None:
    extra = "BT_API_PORT=49271\nBT_WEB_PORT=49272\n" if custom_ports else ""
    services = _rendered(tmp_path / "project", REQUIRED_ENV + extra)["services"]
    for service, target, published in [
        ("api", 8000, "49271" if custom_ports else "8000"),
        ("web", 3000, "49272" if custom_ports else "3000"),
    ]:
        assert services[service]["ports"] == [
            {
                "mode": "ingress",
                "host_ip": "127.0.0.1",
                "target": target,
                "published": published,
                "protocol": "tcp",
            }
        ]
    for service in ("db", "redis", "worker"):
        assert not services[service].get("ports")


def test_explicit_runtime_env_file_does_not_load_the_default(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    runtime = project / "runtime.env"
    runtime.write_text("APP__ENV=packaging-contract\n")
    model = _rendered(
        project / "compose",
        REQUIRED_ENV + f"BT_ENV_FILE={runtime}\nAPP__ENV=must-not-load\n",
    )
    for service in ("api", "worker"):
        assert model["services"][service]["environment"]["APP__ENV"] == "packaging-contract"
