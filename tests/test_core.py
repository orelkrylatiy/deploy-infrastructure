import os
import tempfile
import unittest
from pathlib import Path

from deploy_manager.config import ConfigError, validate_release_id, validate_slug
from deploy_manager.filesystem import FilesystemError, atomic_symlink, current_release, copy_tree


class ValidationTests(unittest.TestCase):
    def test_slug(self):
        self.assertEqual(validate_slug("my-site"), "my-site")
        for value in ("../site", "MySite", "a/b", "-bad", "bad_"):
            with self.subTest(value=value), self.assertRaises(ConfigError):
                validate_slug(value)

    def test_release_id(self):
        self.assertEqual(validate_release_id("a1b2c3"), "a1b2c3")
        for value in ("../bad", ".", "bad/name", "bad value"):
            with self.subTest(value=value), self.assertRaises(ConfigError):
                validate_release_id(value)


class FilesystemTests(unittest.TestCase):
    def test_atomic_symlink_and_current_release(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "releases" / "r1").mkdir(parents=True)
            (root / "releases" / "r2").mkdir()
            atomic_symlink(root, "r1")
            self.assertEqual(current_release(root), "r1")
            atomic_symlink(root, "r2")
            self.assertEqual(current_release(root), "r2")
            self.assertEqual(os.readlink(root / "current"), "releases/r2")

    def test_refuses_to_replace_real_current_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "releases" / "r1").mkdir(parents=True)
            (root / "current").mkdir()
            with self.assertRaises(FilesystemError):
                atomic_symlink(root, "r1")

    def test_copy_tree_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "target").write_text("safe")
            (source / "link").symlink_to(source / "target")
            with self.assertRaises(FilesystemError):
                copy_tree(source, root / "destination")

    def test_copy_tree_copies_regular_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "index.html").write_text("hello")
            destination = root / "destination"
            copy_tree(source, destination)
            self.assertEqual((destination / "index.html").read_text(), "hello")


if __name__ == "__main__":
    unittest.main()
