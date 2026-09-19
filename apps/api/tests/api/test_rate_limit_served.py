"""Rate limiting behind the server the image really starts, not the in-process transport.

uvicorn, left to its defaults, trusts ``X-Forwarded-For`` from a loopback peer and rewrites
``request.client`` from it before the application runs. ``RATE_LIMIT__TRUST_PROXY`` is
meant to be the only switch for that header, so the Dockerfile's ``CMD`` is what is
launched here (its host and port replaced by a free loopback port) and driven over TCP.

No PostgreSQL and no Redis: both are down, the limiter fails open to per-process counting,
and a request without a token is answered 401 before a database is needed.
"""

import json
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

ANONYMOUS_LIMIT = 3
API_ROOT = Path(__file__).resolve().parents[2]
STARTUP_TIMEOUT_SECONDS = 20.0


def _image_command() -> list[str]:
    """The exec-form ``CMD`` of the API image: the argv its container starts."""
    instructions = (API_ROOT / "Dockerfile").read_text().splitlines()
    commands = [line.removeprefix("CMD ") for line in instructions if line.startswith("CMD ")]
    argv = json.loads(commands[-1])  # as docker does: the last CMD wins
    assert isinstance(argv, list)
    return [str(argument) for argument in argv]


def _on_loopback(argv: list[str], port: int) -> list[str]:
    """The same command, run by this interpreter and bound to ``127.0.0.1:port``."""
    assert argv[0] == "uvicorn"
    local = [sys.executable, "-m", "uvicorn", *argv[1:]]
    local[local.index("--host") + 1] = "127.0.0.1"
    local[local.index("--port") + 1] = str(port)
    return local


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port: int = listener.getsockname()[1]
        return port


def _wait_until_serving(server: subprocess.Popen[bytes], base_url: str) -> None:
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        assert server.poll() is None, "the server exited before it answered"
        try:
            if httpx.get(f"{base_url}/health", timeout=1.0).status_code == 200:
                return
        except httpx.TransportError:
            time.sleep(0.1)
    pytest.fail("the server did not answer /health in time")


@pytest.fixture
def served_api(minimal_env: pytest.MonkeyPatch) -> Iterator[str]:
    """Base URL of the API started with the image's own command; the child inherits the env."""
    minimal_env.setenv("RATE_LIMIT__ANONYMOUS__LIMIT", str(ANONYMOUS_LIMIT))
    minimal_env.setenv("RATE_LIMIT__TRUST_PROXY", "false")
    port = _free_port()
    server = subprocess.Popen(  # noqa: S603  (argv from the repo's own Dockerfile, no shell)
        _on_loopback(_image_command(), port),
        cwd=API_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        base_url = f"http://127.0.0.1:{port}"
        _wait_until_serving(server, base_url)
        yield base_url
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait()


def test_a_loopback_peer_cannot_forge_its_address_when_no_proxy_is_trusted(
    served_api: str,
) -> None:
    """A fresh ``X-Forwarded-For`` per request must not be a fresh budget per request."""
    with httpx.Client(base_url=served_api, timeout=5.0) as loopback_peer:
        responses = [
            loopback_peer.get("/tasks", headers={"X-Forwarded-For": f"198.51.100.{n}"})
            for n in range(ANONYMOUS_LIMIT + 1)
        ]

    assert [response.status_code for response in responses] == [401] * ANONYMOUS_LIMIT + [429]
