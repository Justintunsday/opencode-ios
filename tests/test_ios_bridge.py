"""Exercise the packaged optional launcher, including paths with shell punctuation."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / 'packaging/rootless/usr/bin/opencode-ios-bridge'
SHELL = (r'C:\Program Files\Git\bin\bash.exe' if os.name == 'nt' else shutil.which('sh'))


@unittest.skipUnless(SHELL and Path(SHELL).is_file(), 'POSIX shell unavailable')
class LauncherTests(unittest.TestCase):
    def run_launcher(self, root, *args):
        env = dict(os.environ, IOS_BRIDGE_PYTHON=Path(sys.executable).as_posix())
        return subprocess.run([SHELL, LAUNCHER.as_posix(), '--icb-root', root.as_posix(), *args],
                              env=env, cwd=root.parent, capture_output=True, text=True,
                              encoding='utf-8', timeout=30)

    def test_missing_installation_reports_the_actionable_dependency(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_launcher(Path(directory) / "missing space & quote's")
            self.assertEqual(result.returncode, 1)
            self.assertIn('update ios-control-bridge', result.stderr)
            self.assertFalse(result.stdout)

    @unittest.skipUnless(os.environ.get('IOS_CONTROL_BRIDGE_TEST_ROOT') and os.environ.get('IOSREMOTE_BRIDGE_TEST_ROOT'),
                         'set both bridge test roots for the full integration')
    def test_all_three_projects_work_from_packaged_python_files_without_tools_directory(self):
        icb = Path(os.environ['IOS_CONTROL_BRIDGE_TEST_ROOT'])
        irb = Path(os.environ['IOSREMOTE_BRIDGE_TEST_ROOT'])
        with tempfile.TemporaryDirectory(prefix="bridge package space & quote's-") as directory:
            base = Path(directory)
            package = base / 'ios-control-bridge'
            for folder in ('src', 'bin', 'skills'):
                shutil.copytree(icb / folder, package / folder, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            backend = base / 'iosremotebridge'
            automation = backend / 'automation'
            automation.mkdir(parents=True)
            for name in ('__init__.py', '__main__.py', 'client.py', 'protocol.py', 'mcp_tools.py', 'mcp_stdio.py', 'mcp_server.py'):
                shutil.copyfile(irb / 'automation' / name, automation / name)
            self.assertFalse((package / 'tools').exists())
            pairing = base / 'private pairing.json'
            pairing.write_text('PAIRING_SECRET_NOT_JSON', encoding='utf-8')
            config = base / 'opencode.jsonc'
            config.write_text('// keep\n{"model":"existing/provider-model"}\n', encoding='utf-8')
            args = ['--bridge-root', backend.as_posix(), '--config', pairing.as_posix(),
                    '--opencode-config', config.as_posix()]
            setup = self.run_launcher(package, 'setup', *args, '--apply')
            self.assertEqual(setup.returncode, 0, setup.stderr + setup.stdout)
            doctor = self.run_launcher(package, 'doctor', *args)
            self.assertEqual(doctor.returncode, 0, doctor.stderr + doctor.stdout)
            result = json.loads(doctor.stdout)
            self.assertTrue(result['ready'])
            self.assertEqual(result['mcp_stdio']['tool_count'], 14)
            self.assertFalse(result['device_connection_tested'])
            self.assertIn('// keep', config.read_text(encoding='utf-8'))
            self.assertIn('existing/provider-model', config.read_text(encoding='utf-8'))
            self.assertNotIn('PAIRING_SECRET', setup.stdout + doctor.stdout)


if __name__ == '__main__':
    unittest.main()
