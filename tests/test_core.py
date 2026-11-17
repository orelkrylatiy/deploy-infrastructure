import logging
import os
import tempfile
import unittest
import tomllib
from pathlib import Path
from unittest.mock import patch

from deploy_manager.config import ConfigError, ProjectConfig, load_config, validate_release_id, validate_slug
from deploy_manager.engine import DeployError, deploy
from deploy_manager.filesystem import FilesystemError, atomic_symlink, current_release, copy_tree, incoming_path, validate_tree


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
                '[project]\ntype="service"\ndelivery="artifact"\n'
                '[service]\nunit="api.service"\n',
                encoding="utf-8",
            )
            with patch("deploy_manager.config.CONFIG_ROOT", config_root):
                self.assertEqual(load_config("api").service_unit, "api.service")
                (config_root / "api.toml").write_text(
                    '[project]\ntype="service"\ndelivery="artifact"\n'
                    '[service]\nunit="api.sh"\n',
                    encoding="utf-8",
                )
                with self.assertRaises(ConfigError):
                    load_config("api")

    def test_static_projects_reject_shared_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            config_root = Path(temporary)
            (config_root / "site.toml").write_text(
                '[project]\\ntype="static"\\ndelivery="artifact"\\nshared_files=[".env"]\\n',
                encoding="utf-8",
            )
            with patch("deploy_manager.config.CONFIG_ROOT", config_root):
                with self.assertRaises(ConfigError):
                    load_config("site")

    def test_duplicate_shared_paths_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            config_root = Path(temporary)
            (config_root / "site.toml").write_text(
                '[project]\\ntype="static"\\ndelivery="artifact"\\nshared_dirs=["uploads", "uploads"]\\n',
                encoding="utf-8",
            )
            with patch("deploy_manager.config.CONFIG_ROOT", config_root):
                with self.assertRaises(ConfigError):
                    load_config("site")

    def test_healthcheck_url_rejects_credentials_and_invalid_ports(self):
        with tempfile.TemporaryDirectory() as temporary:
            config_root = Path(temporary)
            path = config_root / "api.toml"
            with patch("deploy_manager.config.CONFIG_ROOT", config_root):
                for url in ("https://user:pass@example.com/health", "http://localhost:99999/health", "ftp://example.com"):
                    path.write_text(
                        '[project]\\ntype="static"\\ndelivery="artifact"\\n'
                        f'healthcheck_url="{url}"\\n',
                        encoding="utf-8",
                    )
                    with self.subTest(url=url), self.assertRaises(ConfigError):
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

    def test_explicit_shared_root_allows_only_symlinks_into_that_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            shared = root / "shared"
            source.mkdir()
            shared.mkdir()
            (shared / "uploads").mkdir()
            (shared / "uploads" / "image.png").write_bytes(b"image")
            (source / "uploads").symlink_to(shared / "uploads")
            with self.assertRaises(FilesystemError):
                validate_tree(source, allow_internal_symlinks=True)
            validate_tree(
                source,
                allow_internal_symlinks=True,
                allowed_symlink_roots=(shared,),
            )

    def test_incoming_path_rejects_invalid_project_slug(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch("deploy_manager.filesystem.INCOMING_ROOT", Path(temporary)):
                with self.assertRaises(ConfigError):
                    incoming_path("../outside", "r1", "payload")

    def test_absolute_internal_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            target = source / "target"
            target.write_text("safe")
            (source / "link").symlink_to(target)
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

    def test_static_source_builds_and_publishes_dist(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            incoming = root / "incoming"
            source = self._incoming(incoming, "source-1", kind="source")
            (source / "package.json").write_text("{}")
            command = (
                "python3", "-c",
                "from pathlib import Path; Path('dist').mkdir(); Path('dist/index.html').write_text('built')",
            )
            config = self._config(root, delivery="source", commands=(command,))
            logger = logging.getLogger("test-static-source")
            logger.addHandler(logging.NullHandler())
            patches = self._patched_paths(root, incoming)
            with patches[0], patches[1], patches[2]:
                deploy(config, "source-1", logger)
                self.assertEqual((config.root / "current" / "index.html").read_text(), "built")

    def _service_config(self, root, delivery="artifact", commands=(), shared_files=(), shared_dirs=()):
        return ProjectConfig(
            name="sample", app_type="service", delivery=delivery,
            root=root / "projects" / "sample", keep_releases=5,
            healthcheck_url=None, build_commands=commands, build_output="dist",
            build_timeout=60, shared_files=shared_files, shared_dirs=shared_dirs,
            service_unit="sample.service",
        )

    def test_service_artifact_deploys_with_internal_runtime_symlinks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            incoming = root / "incoming"
            payload = self._incoming(incoming, "service-artifact")
            (payload / "server.js").write_text("console.log('ok')")
            (payload / "node_modules" / ".bin").mkdir(parents=True)
            (payload / "node_modules" / "tool.js").write_text("module.exports = true")
            (payload / "node_modules" / ".bin" / "tool").symlink_to("../tool.js")
            config = self._service_config(root)
            logger = logging.getLogger("test-service-artifact")
            logger.addHandler(logging.NullHandler())
            patches = self._patched_paths(root, incoming)
            with patches[0], patches[1], patches[2], patch("deploy_manager.engine._systemctl"):
                deploy(config, "service-artifact", logger)
                self.assertEqual(current_release(config.root), "service-artifact")
                self.assertTrue((config.root / "current" / "server.js").is_file())

    def test_service_source_builds_and_publishes_runtime(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            incoming = root / "incoming"
            source = self._incoming(incoming, "service-source", kind="source")
            (source / "package.json").write_text("{}")
            command = ("python3", "-c", "from pathlib import Path; Path('server.js').write_text('ready')")
            config = self._service_config(root, delivery="source", commands=(command,))
            logger = logging.getLogger("test-service-source")
            logger.addHandler(logging.NullHandler())
            patches = self._patched_paths(root, incoming)
            with patches[0], patches[1], patches[2], patch("deploy_manager.engine._systemctl"):
                deploy(config, "service-source", logger)
                self.assertTrue((config.root / "current" / "server.js").is_file())

    def test_service_source_supports_shared_files_and_directories(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            incoming = root / "incoming"
            source = self._incoming(incoming, "service-shared", kind="source")
            (source / ".env").write_text("SECRET=kept", encoding="utf-8")
            (source / "uploads").mkdir()
            (source / "uploads" / "avatar.png").write_bytes(b"avatar")
            command = (
                "python3", "-c",
                "from pathlib import Path; Path('server.js').write_text('ready')",
            )
            config = self._service_config(
                root,
                delivery="source",
                commands=(command,),
                shared_files=(".env",),
                shared_dirs=("uploads",),
            )
            logger = logging.getLogger("test-service-source-shared")
            logger.addHandler(logging.NullHandler())
            patches = self._patched_paths(root, incoming)
            with patches[0], patches[1], patches[2], patch("deploy_manager.engine._systemctl"):
                deploy(config, "service-shared", logger)
                current = config.root / "current"
                self.assertTrue((current / ".env").is_symlink())
                self.assertTrue((current / "uploads").is_symlink())
                self.assertEqual((current / ".env").read_text(encoding="utf-8"), "SECRET=kept")
                self.assertEqual((current / "uploads" / "avatar.png").read_bytes(), b"avatar")
                self.assertTrue((config.root / "shared" / ".env").is_file())

    def test_abandoned_staging_directory_is_removed_after_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            incoming = root / "incoming"
            config = self._config(root)
            stale = config.root / "releases" / ".staging-interrupted"
            stale.mkdir(parents=True)
            payload = self._incoming(incoming, "r1")
            (payload / "index.html").write_text("ready", encoding="utf-8")
            logger = logging.getLogger("test-stale-staging")
            logger.addHandler(logging.NullHandler())
            patches = self._patched_paths(root, incoming)
            with patches[0], patches[1], patches[2]:
                deploy(config, "r1", logger)
            self.assertFalse(stale.exists())

    def test_failed_deployment_removes_its_incoming_upload(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            incoming = root / "incoming"
            config = self._config(root)
            payload = self._incoming(incoming, "r1")
            (payload / "index.html").write_text("broken", encoding="utf-8")
            logger = logging.getLogger("test-failed-upload-cleanup")
            logger.addHandler(logging.NullHandler())
            patches = self._patched_paths(root, incoming)
            with patches[0], patches[1], patches[2], patch(
                "deploy_manager.engine._healthcheck",
                side_effect=DeployError("simulated healthcheck failure"),
            ):
                with self.assertRaises(DeployError):
                    deploy(config, "r1", logger)
            self.assertFalse((incoming / "sample" / "r1").exists())

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
                self.assertEqual((config.root / "current" / ".env").read_text(), "SECRET=original")


if __name__ == "__main__":
    unittest.main()
