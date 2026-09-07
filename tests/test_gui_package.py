"""Package transaction checks without installing anything on the test host."""
import runpy
import tempfile
import unittest
from pathlib import Path

MODULE = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts/build_gui_package.py'))


class AppPackageTests(unittest.TestCase):
    def test_generated_installer_scripts_compile(self):
        for name in ('PREINSTALL', 'POSTINSTALL'):
            compile("EXPECTED = {}\n" + MODULE['COMMON'] + MODULE[name], name, 'exec')

    def transaction(self, failure):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            namespace = {'EXPECTED': {'version': 'test', 'commit_url': 'test'}}
            exec(MODULE['COMMON'], namespace)
            app, new = folder / 'app', folder / 'new'
            app.mkdir()
            (app / 'old').write_text('original')
            new.mkdir()
            (new / 'new').write_text('replacement')
            def verify(path):
                if path.name == failure:
                    raise RuntimeError('injected verification failure')
            namespace.update(APP=app, NEW=new, PREVIOUS=folder / 'previous',
                LINK=folder / 'shortcut', RESULT=folder / 'result.json',
                preflight=lambda: folder, verify=verify, run=lambda *args: None,
                check_link=lambda: None, cleanup=lambda home: [])
            if failure:
                with self.assertRaises(SystemExit):
                    exec(MODULE['POSTINSTALL'], namespace)
                self.assertEqual((app / 'old').read_text(), 'original')
                self.assertFalse((app / 'new').exists())
            else:
                exec(MODULE['POSTINSTALL'], namespace)
                self.assertEqual((app / 'new').read_text(), 'replacement')
                self.assertFalse((folder / 'previous').exists())
                self.assertTrue((folder / 'result.json').is_file())

    def test_payload_failure_preserves_original(self):
        self.transaction('new')

    def test_validation_after_swap_restores_original(self):
        self.transaction('app')

    def test_success_removes_temporary_previous_app(self):
        self.transaction(None)
