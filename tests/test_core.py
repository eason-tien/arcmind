# -*- coding: utf-8 -*-
"""
ArcMind Core Smoke Tests
Validates that critical modules can be imported and basic structures work.
"""
import importlib
import os
import sys

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestImports:
    """Verify all core modules can be imported without errors."""

    def test_import_main(self):
        import main  # noqa: F401

    def test_import_config(self):
        from config import settings  # noqa: F401

    def test_import_api_server(self):
        from api import server  # noqa: F401

    def test_import_model_router(self):
        from runtime import model_router  # noqa: F401

    def test_import_skill_manager(self):
        from runtime import skill_manager  # noqa: F401

    def test_import_main_loop(self):
        from loop import main_loop  # noqa: F401

    def test_import_memory(self):
        from memory import working_memory  # noqa: F401

    def test_import_version(self):
        from version import __version__
        assert __version__


class TestVersion:
    """Verify version file is valid."""

    def test_version_file_exists(self):
        version_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "VERSION"
        )
        assert os.path.exists(version_path)

    def test_version_format(self):
        version_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "VERSION"
        )
        with open(version_path) as f:
            version = f.read().strip()
        parts = version.split(".")
        assert len(parts) >= 2, f"Version should be X.Y or X.Y.Z, got: {version}"


class TestConfig:
    """Verify configuration basics."""

    def test_env_example_exists(self):
        env_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            ".env.example"
        )
        assert os.path.exists(env_path)

    def test_env_example_has_required_vars(self):
        env_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            ".env.example"
        )
        with open(env_path) as f:
            content = f.read()
        assert "ARCMIND_API_KEY" in content
        assert "ARCMIND_PORT" in content


class TestSkillManifest:
    """Verify skill manifest is valid."""

    def test_manifest_exists(self):
        manifest_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "skills", "__manifest__.yaml"
        )
        assert os.path.exists(manifest_path)

    def test_skills_directory_has_files(self):
        skills_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "skills"
        )
        py_files = [f for f in os.listdir(skills_dir) if f.endswith('.py') and f != '__init__.py']
        assert len(py_files) > 10, f"Expected 10+ skills, found {len(py_files)}"
