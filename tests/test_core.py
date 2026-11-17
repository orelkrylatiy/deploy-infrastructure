import logging
import os
import tempfile
import unittest
import tomllib
from pathlib import Path
from unittest.mock import patch

from deploy_manager.config import ConfigError, ProjectConfig, load_config, validate_release_id, validate_slug
from deploy_manager.engine import DeployError, deploy
from deploy_manager.filesystem import FilesystemError, atomic_symlink, current_release, copy_tree, validate_tree


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

    def test_service_unit_suffix_is_validated(self):
        with tempfile.TemporaryDirectory() as temporary:
            config_root = Path(temporary)
            (config_root / "api.toml").write_text(
                '[project]\\ntype="service"\\ndelivery="artifact"\\n'
                '[service]\\nunit="api.service"\\n',
                encoding="utf-8",
            )
            with patch("deploy_manager.config.CONFIG_ROOT", config_root):
                self.assertEqual(load_config("api").service_unit, "api.service")
                (config_root / "api.toml").write_text(
                    '[project]\\ntype="service"\\ndelivery="artifact"\\n'
                    '[service]\\nunit="api.sh"\\n',
                    encoding="utf-8",
                )
                with self.assertRaises(ConfigError):
                    load_config("api")

    def test_all_four_example_configs_are_valid_toml(self):
        root = Path(__file__).resolve().parents[1] / "examples" / "project-config"
        for path in root.glob("*.toml"):
            with self.subTest(path=path.name):
                with path.open("rb") as stream:
                    data = tomllib.load(stream)
                self.assertIn(data["project"]["type"], {"static", "service"})
                self.assertIn(data["project"]["delivery"], {"artifact", "source"})


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

    def test_internal_symlink_is_allowed_only_for_service_trees(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "target").write_text("safe")
            (source / "link").symlink_to("target")
            with self.assertRaises(FilesystemError):
                validate_tree(source)
            validate_tree(source, allow_internal_symlinks=True)

    def test_external_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outside = root / "outside"
            outside.write_text("private")
            source = root / "source"
            source.mkdir()
            (source / "link").symlink_to(outside)
            with self.assertRaises(FilesystemError):
                validate_tree(source, allow_internal_symlinks=True)

    def test_copy_tree_copies_regular_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "index.html").write_text("hello")
            destination = root / "destination"
            copy_tree(source, destination)
            self.assertEqual((destination / "index.html").read_text(), "hello")


class DeploymentTests(unittest.TestCase):
    def _config(self, root, delivery="artifact", commands=(), shared_files=(), shared_dirs=()):
        return ProjectConfig(
            name="sample", app_type="static", delivery=delivery,
            root=root / "projects" / "sample", keep_releases=5,
            healthcheck_url=None, build_commands=commands, build_output="dist",
            build_timeout=60, shared_files=shared_files, shared_dirs=shared_dirs,
            service_unit=None,
        )

    def _incoming(self, incoming, release_id, kind="payload"):
        path = incoming / "sample" / release_id / kind
        path.mkdir(parents=True)
        return path

    def _patched_paths(self, root, incoming):
        return (
            patch("deploy_manager.filesystem.PROJECTS_ROOT", root / "projects"),
            patch("deploy_manager.filesystem.INCOMING_ROOT", incoming),
            patch("deploy_manager.engine.INCOMING_ROOT", incoming),
        )

    def test_static_artifact_deploys_and_switches_current(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            incoming = root / "incoming"
            payload = self._incoming(incoming, "r1")
            (payload / "index.html").write_text("release one")
            config = self._config(root)
            logger = logging.getLogger("test-deploy-static")
            logger.addHandler(logging.NullHandler())
            patches = self._patched_paths(root, incoming)
            with patches[0], patches[1], patches[2]:
                deploy(config, "r1", logger)
                self.assertEqual(current_release(config.root), "r1")
                self.assertEqual((config.root / "current" / "index.html").read_text(), "release one")

    def test_failed_healthcheck_restores_previous_release(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            incoming = root / "incoming"
            config = self._config(root)
            logger = logging.getLogger("test-deploy-rollback")
            logger.addHandler(logging.NullHandler())
            patches = self._patched_paths(root, incoming)
            with patches[0], patches[1], patches[2]:
                first = self._incoming(incoming, "r1")
                (first / "index.html").write_text("known good")
                deploy(config, "r1", logger)

                second = self._incoming(incoming, "r2")
                (second / "index.html").write_text("broken")
                with patch("deploy_manager.engine._healthcheck", side_effect=DeployError("simulated failure")):
                    with self.assertRaises(DeployError):
                        deploy(config, "r2", logger)

                self.assertEqual(current_release(config.root), "r1")
                self.assertEqual((config.root / "current" / "index.html").read_text(), "known good")

    def test_shared_file_survives_later_release(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            incoming = root / "incoming"
            config = self._config(root, shared_files=(".env",))
            logger = logging.getLogger("test-deploy-shared")
            logger.addHandler(logging.NullHandler())
            patches = self._patched_paths(root, incoming)
            with patches[0], patches[1], patches[2]:
                first = self._incoming(incoming, "r1")
                (first / "index.html").write_text("one")
                (first / ".env").write_text("SECRET=original")
                deploy(config, "r1", logger)

                second = self._incoming(incoming, "r2")
                (second / "index.html").write_text("two")
                (second / ".env").write_text("SECRET=overwritten")
                deploy(config, "r2", logger)

                self.assertEqual((config.root / "shared" / ".env").read_text(), "SECRET=original")
                self.assertTrue((config.root / "current" / ".env").is_symlink())


if __name__ == "__main__":
    unittest.main()
