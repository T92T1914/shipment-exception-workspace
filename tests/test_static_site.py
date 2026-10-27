"""Static payload admission regressions. No application, credentials or DB fixture."""
import importlib.util
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("shipment_static_site", ROOT / "tools/build_site.py")
site = importlib.util.module_from_spec(spec)
spec.loader.exec_module(site)


class StaticSiteTests(unittest.TestCase):
    def fixture(self, root):
        import json
        inputs = json.loads((ROOT / "docs/workflow-rendering.json").read_text())["inputs"]
        for source in set(site.FILES) | set(inputs):
            target = root / source
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / source, target)

    def test_payload_is_static_and_whitelisted(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "source"
            self.fixture(root)
            record = site.build(Path(temp) / "published", root)
            self.assertEqual(set(record["files"]), set(site.FILES.values()))
            self.assertFalse(any("schema.sql" in p or ".env" in p for p in record["files"]))

    def test_unreviewed_source_file_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            (root / "site/unreviewed.txt").write_text("synthetic fixture")
            with self.assertRaisesRegex(ValueError, "allowlist"):
                site.validate(root)

    def test_missing_narrow_image_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            (root / "docs/assets/workflow-obscur-narrow.png").unlink()
            with self.assertRaisesRegex(ValueError, "Missing static source"):
                site.validate(root)

    def test_changed_figure_requires_a_fresh_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            image = root / "docs/assets/workflow-obscur-wide.png"
            image.write_bytes(image.read_bytes() + b"changed-fixture")
            with self.assertRaisesRegex(ValueError, "Stale conceptual-figure"):
                site.validate(root)

    def test_broken_internal_navigation_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            page = root / "site/index.html"
            page.write_text(page.read_text().replace('id="example"', 'id="other"'))
            with self.assertRaisesRegex(ValueError, "Missing visitor route"):
                site.validate(root)


if __name__ == "__main__":
    unittest.main()
