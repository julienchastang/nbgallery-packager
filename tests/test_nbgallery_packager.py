import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

import nbgallery_packager as packager


def write_notebook(path, markdown=None):
    cells = []
    if markdown is not None:
        cells.append({"cell_type": "markdown", "source": markdown})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"cells": cells}), encoding="utf-8")


class NbgalleryPackagerTests(unittest.TestCase):
    def test_nested_notebooks_are_flattened_with_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo = root / "repo"
            staging = root / "staging"
            write_notebook(
                repo / "example-notebook.ipynb",
                "# Example Notebook\n\nExample notebook description with enough detail",
            )
            write_notebook(
                repo / "tutorials" / "basics" / "demo.ipynb",
                ["## Demo notebook\n", "Useful details for the demo notebook."],
            )

            config = {
                "owner": "Test Group",
                "owner_type": "Group",
                "updater": "Test User",
                "creator": "Test User",
                "public": True,
                "tags": ["training", "example"],
            }
            staged, metadata, warnings = packager.stage_notebooks(repo, staging, config)

            self.assertEqual(
                staged,
                [
                    (Path("example-notebook.ipynb"), "example-notebook.ipynb"),
                    (
                        Path("tutorials/basics/demo.ipynb"),
                        "tutorials__basics__demo.ipynb",
                    ),
                ],
            )
            self.assertTrue((staging / "example-notebook.ipynb").exists())
            self.assertTrue((staging / "tutorials__basics__demo.ipynb").exists())

            metadata = json.loads((staging / "metadata.json").read_text())
            self.assertEqual(metadata["example-notebook"]["title"], "Example Notebook")
            self.assertEqual(
                metadata["example-notebook"]["description"],
                "Example notebook description with enough detail",
            )
            self.assertEqual(
                metadata["tutorials__basics__demo"]["title"], "Demo notebook"
            )
            self.assertEqual(
                metadata["tutorials__basics__demo"]["description"],
                "Useful details for the demo notebook.",
            )
            self.assertEqual(metadata["tutorials__basics__demo"]["owner"], "Test Group")
            self.assertEqual(metadata["tutorials__basics__demo"]["updater"], "Test User")
            self.assertEqual(metadata["tutorials__basics__demo"]["creator"], "Test User")
            self.assertEqual(
                metadata["tutorials__basics__demo"]["tags"], ["training", "example"]
            )
            self.assertEqual(warnings, [])

    def test_path_prefixes_are_stripped_before_flattening(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo = root / "repo"
            staging = root / "staging"
            write_notebook(
                repo / "notebooks" / "convective" / "MUCAPE.ipynb",
                "Convective notebook description",
            )
            write_notebook(
                repo / "examples" / "notebooks" / "demo.ipynb",
                "Nested notebook description",
            )

            staged, metadata, warnings = packager.stage_notebooks(
                repo,
                staging,
                {
                    "owner": "Test Group",
                    "owner_type": "Group",
                    "updater": "Test User",
                    "creator": "Test User",
                    "strip_path_prefixes": ["notebooks"],
                },
            )

            self.assertEqual(
                staged,
                [
                    (
                        Path("examples/notebooks/demo.ipynb"),
                        "examples__notebooks__demo.ipynb",
                    ),
                    (
                        Path("notebooks/convective/MUCAPE.ipynb"),
                        "convective__MUCAPE.ipynb",
                    ),
                ],
            )
            self.assertTrue((staging / "convective__MUCAPE.ipynb").exists())
            self.assertTrue((staging / "examples__notebooks__demo.ipynb").exists())
            self.assertIn("convective__MUCAPE", metadata)
            self.assertIn("examples__notebooks__demo", metadata)
            self.assertEqual(warnings, [])

    def test_collisions_fail_clearly(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo = root / "repo"
            write_notebook(repo / "foo__bar.ipynb", "Top level")
            write_notebook(repo / "foo" / "bar.ipynb", "Nested")

            with self.assertRaisesRegex(ValueError, "Notebook name collision"):
                packager.stage_notebooks(
                    repo,
                    root / "staging",
                    {
                        "owner": "Test Group",
                        "owner_type": "Group",
                        "updater": "Test User",
                        "creator": "Test User",
                    },
                )

    def test_stripped_prefix_collisions_fail_clearly(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo = root / "repo"
            write_notebook(repo / "convective" / "MUCAPE.ipynb", "Top level")
            write_notebook(repo / "notebooks" / "convective" / "MUCAPE.ipynb", "Nested")

            with self.assertRaisesRegex(ValueError, "Notebook name collision"):
                packager.stage_notebooks(
                    repo,
                    root / "staging",
                    {
                        "owner": "Test Group",
                        "owner_type": "Group",
                        "updater": "Test User",
                        "creator": "Test User",
                        "strip_path_prefixes": ["notebooks"],
                    },
                )

    def test_missing_markdown_uses_default_description(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo = root / "repo"
            staging = root / "staging"
            write_notebook(repo / "example.ipynb")

            staged, metadata, warnings = packager.stage_notebooks(
                repo,
                staging,
                {
                    "owner": "Test Group",
                    "owner_type": "Group",
                    "updater": "Test User",
                    "creator": "Test User",
                },
            )

            self.assertEqual(
                metadata["example"]["description"], packager.DEFAULT_DESCRIPTION
            )
            self.assertIn("example.ipynb: no markdown cell", warnings)
            self.assertIn("example.ipynb: fallback description used", warnings)

    def test_short_markdown_uses_default_description_with_warning(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo = root / "repo"
            staging = root / "staging"
            write_notebook(repo / "example.ipynb", "# Too short")

            staged, metadata, warnings = packager.stage_notebooks(
                repo,
                staging,
                {
                    "owner": "Test Group",
                    "owner_type": "Group",
                    "updater": "Test User",
                    "creator": "Test User",
                },
            )

            self.assertEqual(
                metadata["example"]["description"], packager.DEFAULT_DESCRIPTION
            )
            self.assertIn("example.ipynb: weak/short markdown description", warnings)
            self.assertIn("example.ipynb: fallback description used", warnings)

    def test_description_strips_code_blocks_and_truncates(self):
        long_text = "A" * 300
        description, used_fallback = packager.markdown_to_description(
            f"# Heading\n---\n```python\nprint('hidden')\n```\n{long_text}"
        )

        self.assertFalse(used_fallback)
        self.assertNotIn("hidden", description)
        self.assertNotIn("---", description)
        self.assertEqual(len(description), 250)
        self.assertTrue(description.endswith("..."))

    def test_dry_run_plan_does_not_write_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo = root / "repo"
            staging = root / "staging"
            write_notebook(repo / "example.ipynb", "Example markdown description")

            planned, metadata, warnings = packager.plan_notebooks(
                repo,
                {
                    "owner": "Test Group",
                    "owner_type": "Group",
                    "updater": "Test User",
                    "creator": "Test User",
                },
            )

            self.assertEqual(planned, [(Path("example.ipynb"), "example.ipynb")])
            self.assertEqual(
                metadata["example"]["description"], "Example markdown description"
            )
            self.assertEqual(warnings, [])
            self.assertFalse(staging.exists())

    def test_dry_run_metadata_printout_truncates_descriptions(self):
        long_description = "A" * 120

        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "output.txt"
            original_stdout = sys.stdout
            try:
                with output.open("w", encoding="utf-8") as stdout:
                    sys.stdout = stdout
                    packager.print_summary(
                        [(Path("example.ipynb"), "example.ipynb")],
                        {"example": {"title": "Example", "description": long_description}},
                        [],
                        None,
                        None,
                        True,
                    )
            finally:
                sys.stdout = original_stdout

            text = output.read_text(encoding="utf-8")
            self.assertIn("Example - " + ("A" * 77) + "...", text)

    def test_config_loader_supports_simple_yaml(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text(
                "\n".join(
                    [
                        'owner: "Test Group"',
                        'owner_type: "Group"',
                        'updater: "Test User"',
                        'creator: "Test User"',
                        "public: true",
                        "tags:",
                        "  - training",
                        "  - example",
                        "strip_path_prefixes:",
                        "  - notebooks",
                    ]
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                packager.load_config(config_path),
                {
                    "owner": "Test Group",
                    "owner_type": "Group",
                    "updater": "Test User",
                    "creator": "Test User",
                    "public": True,
                    "tags": ["training", "example"],
                    "strip_path_prefixes": ["notebooks"],
                },
            )

    def test_archive_contains_flat_files_and_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            staging = root / "staging"
            staging.mkdir()
            (staging / "nested").mkdir()
            (staging / "example.ipynb").write_text("{}", encoding="utf-8")
            (staging / "metadata.json").write_text("{}", encoding="utf-8")
            output = root / "upload.tar.gz"

            packager.create_archive(staging, output)

            with tarfile.open(output, "r:gz") as archive:
                names = sorted(archive.getnames())
                self.assertEqual(
                    names, ["example.ipynb", "metadata.json"]
                )
                self.assertNotIn("././@PaxHeader", names)


if __name__ == "__main__":
    unittest.main()
