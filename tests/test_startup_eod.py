from datetime import date, datetime
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

import main


def _touch_for_day(path: Path, day: date) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")
    ts = datetime.combine(day, datetime.min.time()).timestamp()
    path.touch()
    import os
    os.utime(path, (ts, ts))


class StartupEodTests(unittest.TestCase):
    def setUp(self) -> None:
        self.asof = date(2026, 7, 24)
        self.tmpdir = tempfile.TemporaryDirectory()
        self.input_dir = Path(self.tmpdir.name)
        self.fixed_datetime = type("FixedDateTime", (), {
            "today": staticmethod(lambda: datetime(2026, 7, 24, 9, 0, 0)),
            "fromtimestamp": staticmethod(datetime.fromtimestamp),
        })

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def _patched_modules(self):
        settings_general = types.ModuleType("settings.general")

        class FakeDateConfig:
            @classmethod
            def is_cn_workday(cls, _):
                return True

        settings_general.DateConfig = FakeDateConfig

        settings_paths = types.ModuleType("settings.paths")
        settings_paths.DIR_INPUT = self.input_dir

        artifact_service = types.ModuleType("web.services.artifacts")
        artifact_service.find_latest_run = lambda mode=None: type(
            "RunMeta", (), {"asof": self.asof.isoformat(), "status": "completed"}
        )()

        return {
            "settings.general": settings_general,
            "settings.paths": settings_paths,
            "web.services.artifacts": artifact_service,
        }

    def test_should_skip_startup_eod_when_latest_run_and_artifacts_are_fresh(self):
        with patch.object(main, "datetime", self.fixed_datetime), \
             patch.dict("sys.modules", self._patched_modules()):
            for name in main._STARTUP_EOD_ARTIFACTS:
                _touch_for_day(self.input_dir / name, self.asof)

            should_run, reason = main._should_run_startup_eod(Path("d:/AtlasNexus/bin-v4.0"))

        self.assertFalse(should_run)
        self.assertIn("already match", reason)

    def test_should_run_startup_eod_when_cbond_reference_is_stale(self):
        with patch.object(main, "datetime", self.fixed_datetime), \
             patch.dict("sys.modules", self._patched_modules()):
            for name in main._STARTUP_EOD_ARTIFACTS:
                day = self.asof if name != "CBond-cvref.pkl" else date(2026, 7, 23)
                _touch_for_day(self.input_dir / name, day)

            should_run, reason = main._should_run_startup_eod(Path("d:/AtlasNexus/bin-v4.0"))

        self.assertTrue(should_run)
        self.assertIn("CBond-cvref.pkl", reason)

    def test_launch_startup_eod_submits_tracked_eod_update_job(self):
        jobs_service = types.ModuleType("web.services.jobs")
        submitted: list[list[str]] = []

        def start_engine_job(*, argv):
            submitted.append(argv)
            return type("Job", (), {"job_id": "startup-eod"})()

        jobs_service.start_engine_job = start_engine_job

        with patch.object(main, "_should_run_startup_eod", return_value=(True, "stale artifacts")), \
             patch.dict("sys.modules", {"web.services.jobs": jobs_service}):
            started = main._launch_startup_eod(Path("d:/AtlasNexus/bin-v4.0"))

        self.assertTrue(started)
        self.assertEqual(submitted, [["eod", "--update-data"]])


if __name__ == "__main__":
    unittest.main()