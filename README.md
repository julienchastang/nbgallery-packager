# nbgallery-packager

Package notebooks from a public git repository into a flat `.tar.gz` archive for [nbgallery](https://nbgallery.github.io/ "nbgallery") [bulk upload](https://github.com/nbgallery/nbgallery/blob/main/docs/configuration.md "bulk upload").

## Dependencies

Requires Python 3.9+ and PyYAML.

## Install

From this repository:

```bash
python -m pip install -e .
```

## Configuration

Create a YAML config file with the required nbgallery ownership fields:

```yaml
owner: "example_group"
owner_type: "Group"
updater: "example_user"
creator: "example_user"
public: true
tags:
  - training
strip_path_prefixes:
  - notebooks
```

Required fields are `owner`, `owner_type`, `updater`, and `creator`.

The configured users and groups must already exist in nbgallery:

- `owner` must match an existing nbgallery User username or Group name, depending on `owner_type`
- `creator` must match an existing nbgallery username
- `updater` must match an existing nbgallery username

Optional fields:

- `public`
- `tags`
- `strip_path_prefixes`

`strip_path_prefixes` removes matching leading path components before notebooks are flattened. For example, `notebooks/convective/MUCAPE.ipynb` with `strip_path_prefixes: ["notebooks"]` becomes `convective__MUCAPE.ipynb`.

## Usage

Package notebooks from a public repository:

```bash
nbgallery-packager https://github.com/example/project.git --config examples/config.yaml --output nbgallery_upload.tar.gz
```

Preview the planned notebook mapping and metadata without copying files or creating an archive:

```bash
nbgallery-packager https://github.com/example/project.git --config examples/config.yaml --dry-run
```

Keep the staging directory for inspection:

```bash
nbgallery-packager https://github.com/example/project.git --config examples/config.yaml --keep-staging
```

## Archive Contents

The generated archive contains:

- flat `.ipynb` files
- `metadata.json`

Nested notebooks are renamed using `__` separators. For example:

```text
tutorials/basics/demo.ipynb -> tutorials__basics__demo.ipynb
```

If flattened names collide, packaging fails with a clear error.

This archive is intended for upload via the nbgallery admin bulk import interface.

## Run Tests

```bash
python -m unittest
```

## About this project

Most of the code in this repository was generated with the help of AI tools and then reviewed and tested by a human.
