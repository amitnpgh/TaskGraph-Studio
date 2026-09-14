import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import launch_taskgraph as launcher


class LauncherTests(unittest.TestCase):
    def test_missing_gui_is_logged_without_requiring_gui(self):
        fake = types.SimpleNamespace(Tk=Mock(side_effect=RuntimeError("missing Tcl")))
        with patch.object(sys, "argv", ["launcher", "--check-ui"]), \
                patch.dict(sys.modules, {"tkinter": fake}), \
                patch.object(launcher, "log_failure") as log:
            self.assertEqual(launcher.main(), 1)
        self.assertIn("missing Tcl", log.call_args.args[0])

    def test_smoke_test_initializes_and_closes_actual_app_class(self):
        studio = Mock()
        with patch.object(sys, "argv", ["launcher", "--smoke-test"]), \
                patch.dict(sys.modules, {"desktop": types.SimpleNamespace(Studio=studio)}):
            self.assertEqual(launcher.main(), 0)
        studio.return_value.destroy.assert_called_once()
        studio.return_value.mainloop.assert_not_called()

    def test_import_failure_is_retained(self):
        with patch.object(sys, "argv", ["launcher", "--smoke-test"]), \
                patch.dict(sys.modules, {"desktop": None}), \
                patch.object(launcher, "log_failure") as log:
            self.assertEqual(launcher.main(), 1)
        self.assertIn("ModuleNotFoundError", log.call_args.args[0])

    def test_log_contains_interpreter_and_error(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(launcher, "__file__", str(Path(directory) / "launcher.py")):
                path = launcher.log_failure("test failure")
            content = Path(path).read_text(encoding="utf-8")
            self.assertIn(sys.executable, content)
            self.assertIn("test failure", content)


if __name__ == "__main__":
    unittest.main()
