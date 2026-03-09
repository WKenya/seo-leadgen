from __future__ import annotations

import base64
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

HAS_API_DEPS = True
IMPORT_ERROR = ""
try:
    from fastapi.testclient import TestClient
except Exception as exc:  # noqa: BLE001
    HAS_API_DEPS = False
    IMPORT_ERROR = str(exc)


class _FakeDbOk:
    def execute(self, _statement):  # noqa: ANN001
        return 1


class _FakeDbFail:
    def execute(self, _statement):  # noqa: ANN001
        raise RuntimeError("boom")


class HealthAndArtifactRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        if not HAS_API_DEPS:
            self.skipTest(f"api test deps missing: {IMPORT_ERROR}")

        from app.db import get_db
        from app.main import create_app
        from app.settings import get_settings

        self._get_db = get_db
        self._get_settings = get_settings
        self._env_backup = {
            "ARTIFACTS_ROOT": os.environ.get("ARTIFACTS_ROOT"),
            "ARTIFACTS_BASIC_AUTH_USER": os.environ.get("ARTIFACTS_BASIC_AUTH_USER"),
            "ARTIFACTS_BASIC_AUTH_PASS": os.environ.get("ARTIFACTS_BASIC_AUTH_PASS"),
            "WEBHOOK_SHARED_SECRET": os.environ.get("WEBHOOK_SHARED_SECRET"),
            "WEBHOOK_SIGNATURE_SECRET": os.environ.get("WEBHOOK_SIGNATURE_SECRET"),
            "WEBHOOK_SIGNATURE_TOLERANCE_SECONDS": os.environ.get("WEBHOOK_SIGNATURE_TOLERANCE_SECONDS"),
            "POSTMARK_WEBHOOK_TOKEN": os.environ.get("POSTMARK_WEBHOOK_TOKEN"),
            "MAILGUN_WEBHOOK_SIGNING_KEY": os.environ.get("MAILGUN_WEBHOOK_SIGNING_KEY"),
            "MAILGUN_WEBHOOK_SIGNATURE_TOLERANCE_SECONDS": os.environ.get("MAILGUN_WEBHOOK_SIGNATURE_TOLERANCE_SECONDS"),
        }
        os.environ.setdefault("WEBHOOK_SHARED_SECRET", "test_shared_secret")
        os.environ.setdefault("WEBHOOK_SIGNATURE_SECRET", "")
        os.environ.setdefault("WEBHOOK_SIGNATURE_TOLERANCE_SECONDS", "300")
        os.environ.setdefault("POSTMARK_WEBHOOK_TOKEN", "")
        os.environ.setdefault("MAILGUN_WEBHOOK_SIGNING_KEY", "")
        os.environ.setdefault("MAILGUN_WEBHOOK_SIGNATURE_TOLERANCE_SECONDS", "300")

        self._tmpdir = TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)
        artifact_file = self.tmp_path / "shots" / "home.txt"
        artifact_file.parent.mkdir(parents=True, exist_ok=True)
        artifact_file.write_text("artifact-proof", encoding="utf-8")
        self.artifact_relpath = "shots/home.txt"

        os.environ["ARTIFACTS_ROOT"] = str(self.tmp_path)
        os.environ["ARTIFACTS_BASIC_AUTH_USER"] = ""
        os.environ["ARTIFACTS_BASIC_AUTH_PASS"] = ""
        self._get_settings.cache_clear()

        self.app = create_app()
        self.app.dependency_overrides[self._get_db] = lambda: iter([_FakeDbOk()])
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        if not HAS_API_DEPS:
            return
        self.client.close()
        self.app.dependency_overrides.clear()
        self._tmpdir.cleanup()
        for key, value in self._env_backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._get_settings.cache_clear()

    def _set_db_override(self, db_obj) -> None:  # noqa: ANN001
        def _override():
            yield db_obj

        self.app.dependency_overrides[self._get_db] = _override

    def _basic_auth_header(self, username: str, password: str) -> dict[str, str]:
        token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
        return {"Authorization": f"Basic {token}"}

    def test_healthz_and_readyz_success(self) -> None:
        self._set_db_override(_FakeDbOk())
        health = self.client.get("/healthz")
        self.assertEqual(health.status_code, 200, health.text)
        self.assertEqual(health.json()["ok"], True)

        ready = self.client.get("/readyz")
        self.assertEqual(ready.status_code, 200, ready.text)
        self.assertEqual(ready.json(), {"ok": True, "db": "ready"})

    def test_readyz_returns_503_when_db_ping_fails(self) -> None:
        self._set_db_override(_FakeDbFail())
        ready = self.client.get("/readyz")
        self.assertEqual(ready.status_code, 503)
        self.assertIn("db_unready:", ready.json()["detail"])

    def test_artifact_serves_file_without_auth_when_not_configured(self) -> None:
        response = self.client.get(f"/artifacts/{self.artifact_relpath}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.text, "artifact-proof")

    def test_artifact_requires_basic_auth_when_configured(self) -> None:
        os.environ["ARTIFACTS_BASIC_AUTH_USER"] = "u"
        os.environ["ARTIFACTS_BASIC_AUTH_PASS"] = "p"
        self._get_settings.cache_clear()

        unauthorized = self.client.get(f"/artifacts/{self.artifact_relpath}")
        self.assertEqual(unauthorized.status_code, 401)
        self.assertEqual(unauthorized.headers.get("www-authenticate"), "Basic")

        wrong = self.client.get(
            f"/artifacts/{self.artifact_relpath}",
            headers=self._basic_auth_header("u", "wrong"),
        )
        self.assertEqual(wrong.status_code, 401)

        ok = self.client.get(
            f"/artifacts/{self.artifact_relpath}",
            headers=self._basic_auth_header("u", "p"),
        )
        self.assertEqual(ok.status_code, 200, ok.text)
        self.assertEqual(ok.text, "artifact-proof")

    def test_artifact_accepts_lowercase_basic_scheme(self) -> None:
        os.environ["ARTIFACTS_BASIC_AUTH_USER"] = "u"
        os.environ["ARTIFACTS_BASIC_AUTH_PASS"] = "p"
        self._get_settings.cache_clear()

        token = base64.b64encode(b"u:p").decode("ascii")
        response = self.client.get(
            f"/artifacts/{self.artifact_relpath}",
            headers={"Authorization": f"basic {token}"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.text, "artifact-proof")

    def test_artifact_rejects_path_escape(self) -> None:
        response = self.client.get("/artifacts/%2E%2E/etc/passwd")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "invalid artifact path")


if __name__ == "__main__":
    unittest.main()
