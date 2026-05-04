import argparse
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

import yaml


DEFAULT_DESCRIPTION = "Automatically Uploaded"
REQUIRED_CONFIG_KEYS = ("owner", "owner_type", "updater", "creator")


def load_config(path):
    with Path(path).open(encoding="utf-8") as config_file:
        config = yaml.safe_load(config_file) or {}

    if not isinstance(config, dict):
        raise ValueError("Config must be a YAML mapping")

    missing = [key for key in REQUIRED_CONFIG_KEYS if key not in config]
    if missing:
        raise ValueError(f"Missing required config key(s): {', '.join(missing)}")

    if "tags" in config and not isinstance(config["tags"], list):
        raise ValueError("Config key 'tags' must be a list")
    if "strip_path_prefixes" in config and not isinstance(
        config["strip_path_prefixes"], list
    ):
        raise ValueError("Config key 'strip_path_prefixes' must be a list")

    return config


def strip_path_prefix(relative_path, prefixes):
    for prefix in prefixes:
        prefix_path = Path(prefix)
        prefix_parts = prefix_path.parts
        if relative_path.parts[: len(prefix_parts)] == prefix_parts:
            return Path(*relative_path.parts[len(prefix_parts) :])
    return relative_path


def output_name_for(relative_path):
    if len(relative_path.parts) == 1:
        return relative_path.name
    return "__".join(relative_path.parts)


def find_notebooks(repo_dir):
    notebooks = []
    for path in repo_dir.rglob("*.ipynb"):
        if ".git" not in path.relative_to(repo_dir).parts:
            notebooks.append(path)
    return sorted(notebooks)


def title_from_stem(stem):
    return stem.replace("_", " ").replace("-", " ").strip()


def first_markdown_heading(markdown):
    if isinstance(markdown, list):
        markdown = "".join(markdown)
    lines = str(markdown or "").splitlines()

    for index, line in enumerate(lines):
        match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", line)
        if match:
            return match.group(1).strip()
        if index + 1 < len(lines) and re.match(
            r"^\s{0,3}(=+|-+)\s*$", lines[index + 1]
        ):
            heading = line.strip()
            if heading:
                return heading

    return None


def strip_first_markdown_heading(markdown):
    if isinstance(markdown, list):
        markdown = "".join(markdown)
    lines = str(markdown or "").splitlines()

    for index, line in enumerate(lines):
        if re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", line):
            return "\n".join(lines[:index] + lines[index + 1 :])
        if (
            index + 1 < len(lines)
            and re.match(r"^\s{0,3}(=+|-+)\s*$", lines[index + 1])
            and line.strip()
        ):
            return "\n".join(lines[:index] + lines[index + 2 :])

    return markdown


def markdown_to_description(markdown):
    if isinstance(markdown, list):
        markdown = "".join(markdown)
    markdown = str(markdown or "").strip()
    markdown = re.sub(r"```.*?```", "", markdown, flags=re.DOTALL)
    markdown = re.sub(r"~~~.*?~~~", "", markdown, flags=re.DOTALL)
    markdown = re.sub(r"^\s{0,3}#{1,6}\s*", "", markdown, flags=re.MULTILINE)
    markdown = re.sub(r"^\s{0,3}(=+|-+)\s*$", "", markdown, flags=re.MULTILINE)
    markdown = re.sub(r"\s+", " ", markdown).strip()
    if len(markdown) < 20:
        return DEFAULT_DESCRIPTION, True
    if len(markdown) > 250:
        markdown = markdown[:247].rstrip() + "..."
    return markdown, False


def notebook_metadata(path, display_path, fallback_title):
    try:
        notebook = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read notebook '{path}': {error}") from error

    title = None
    first_markdown = None

    for cell in notebook.get("cells", []):
        if cell.get("cell_type") == "markdown":
            source = cell.get("source", "")
            if first_markdown is None:
                first_markdown = source
            if title is None:
                title = first_markdown_heading(source)

    if first_markdown is None:
        return fallback_title, DEFAULT_DESCRIPTION, [
            f"{display_path}: no markdown cell",
            f"{display_path}: fallback description used",
        ]

    description_source = first_markdown
    if first_markdown_heading(description_source):
        description_source = strip_first_markdown_heading(description_source)

    description, used_fallback = markdown_to_description(description_source)
    warnings = []
    if used_fallback:
        warnings.append(f"{display_path}: weak/short markdown description")
        warnings.append(f"{display_path}: fallback description used")

    return title or fallback_title, description, warnings


def plan_notebooks(repo_dir, config):
    metadata = {}
    planned = []
    warnings = []
    seen = {}

    for notebook in find_notebooks(repo_dir):
        relative = notebook.relative_to(repo_dir)
        stripped = strip_path_prefix(relative, config.get("strip_path_prefixes", []))
        output_name = output_name_for(stripped)
        if output_name in seen:
            first = seen[output_name]
            raise ValueError(
                "Notebook name collision after flattening: "
                f"'{first}' and '{relative}' both become '{output_name}'"
            )
        seen[output_name] = relative

        metadata_key = Path(output_name).stem
        title, description, metadata_warnings = notebook_metadata(
            notebook, relative, title_from_stem(metadata_key)
        )
        warnings.extend(metadata_warnings)
        item = {
            "title": title,
            "description": description,
            "owner": config["owner"],
            "owner_type": config["owner_type"],
            "updater": config["updater"],
            "creator": config["creator"],
        }
        for optional_key in ("public", "tags"):
            if optional_key in config:
                item[optional_key] = config[optional_key]
        metadata[metadata_key] = item
        planned.append((relative, output_name))

    return planned, metadata, warnings


def stage_notebooks(repo_dir, staging_dir, config):
    planned, metadata, warnings = plan_notebooks(repo_dir, config)
    staging_dir.mkdir(parents=True, exist_ok=True)
    for relative, output_name in planned:
        shutil.copy2(repo_dir / relative, staging_dir / output_name)

    (staging_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    return planned, metadata, warnings


def create_archive(staging_dir, output_path):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output_path, "w:gz", format=tarfile.GNU_FORMAT) as archive:
        for path in sorted(staging_dir.iterdir()):
            if path.is_file():
                archive.add(path, arcname=path.name, recursive=False)


def clone_repo(repo_url, destination):
    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", repo_url, str(destination)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as error:
        stderr = error.stderr.strip() or "git clone failed"
        raise ValueError(f"Could not clone repository: {stderr}") from error


def truncate_text(text, max_length=80):
    if len(text) <= max_length:
        return text
    return text[: max_length - 3].rstrip() + "..."


def print_summary(planned, metadata, warnings, staging_dir, output_path, dry_run):
    label = "Planned notebooks" if dry_run else "Imported notebooks"
    print(f"{label}: {len(planned)}")
    for source, output_name in planned:
        if str(source) == output_name:
            print(f"  {output_name}")
        else:
            print(f"  {source} -> {output_name}")

    renamed = [
        (source, output_name)
        for source, output_name in planned
        if str(source) != output_name
    ]
    if renamed:
        print("Renamed (flattened paths):")
        for source, output_name in renamed:
            print(f"  {source} -> {output_name}")

    print("Metadata:")
    for key, item in metadata.items():
        description = item["description"]
        if dry_run:
            description = truncate_text(description)
        print(f"  {key}: {item['title']} - {description}")

    if output_path and not dry_run:
        print(f"Archive: {output_path}")
    if staging_dir:
        print(f"Staging: {staging_dir}")
    if dry_run:
        print(
            "Dry run: no files were copied, metadata was not written, "
            "and archive was not created"
        )

    if warnings:
        print("Warnings:")
        for warning in warnings:
            print(f"  {warning}")


def build_package(repo_url, config_path, output_path, keep_staging=False, dry_run=False):
    config = load_config(config_path)
    warnings = []
    temp_root = Path(tempfile.mkdtemp(prefix="nbgallery_packager_"))
    repo_dir = temp_root / "repo"
    staging_dir = temp_root / "staging"

    try:
        clone_repo(repo_url, repo_dir)
        if dry_run:
            planned, metadata, warnings = plan_notebooks(repo_dir, config)
        else:
            planned, metadata, warnings = stage_notebooks(repo_dir, staging_dir, config)

        if not planned:
            warnings.append("No .ipynb files found")

        if not dry_run:
            create_archive(staging_dir, output_path)

        kept_staging = staging_dir if keep_staging else None
        print_summary(planned, metadata, warnings, kept_staging, output_path, dry_run)
        return 0
    finally:
        if keep_staging:
            if repo_dir.exists():
                shutil.rmtree(repo_dir)
        else:
            shutil.rmtree(temp_root, ignore_errors=True)


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Package notebooks from a public git repository for nbgallery upload."
    )
    parser.add_argument("repo_url", help="Public git repository URL")
    parser.add_argument(
        "--config", required=True, help="YAML config with owner metadata"
    )
    parser.add_argument(
        "--output",
        default="nbgallery_upload.tar.gz",
        help="Output .tar.gz path",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Print planned notebook mapping and metadata without copying files "
            "or creating an archive"
        ),
    )
    parser.add_argument(
        "--keep-staging",
        action="store_true",
        help="Keep the temporary staging directory after the run",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])
    try:
        return build_package(
            args.repo_url,
            args.config,
            Path(args.output),
            keep_staging=args.keep_staging,
            dry_run=args.dry_run,
        )
    except (subprocess.CalledProcessError, OSError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
