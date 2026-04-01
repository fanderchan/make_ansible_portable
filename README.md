# make_ansible_portable

English | [简体中文](README.zh-CN.md)

Build official `ansible-base` / `ansible-core` packages into portable Ansible bundles that work after unpacking.

The overall approach is similar to `portable-ansible`:

- Do not modify the official Ansible runtime code.
- Install the official package into a directory with `pip --target`.
- Drop in a custom `__main__.py` launcher.
- Run it with `python3 ./ansible` or `python3 ./ansible-playbook`.
- Install third-party Python dependencies into `ansible/extras`.

## Open Source Notes

- The packaging approach is inspired by [`ownport/portable-ansible`](https://github.com/ownport/portable-ansible).
- [`templates/__main__.py`](templates/__main__.py) was rewritten for this repository and no longer reuses the upstream file header or source text.
- Repository code is released under `Apache-2.0`.
- This project is not affiliated with Ansible, Red Hat, or `ownport/portable-ansible`, and does not represent their official position.
- Generated bundles include official Ansible packages and their dependencies. If you redistribute those artifacts, you must also comply with their licenses.

See [LICENSE](LICENSE), [NOTICE](NOTICE), [ACKNOWLEDGEMENTS.md](ACKNOWLEDGEMENTS.md), [CONTRIBUTING.md](CONTRIBUTING.md), [CHANGELOG.md](CHANGELOG.md), and [SECURITY.md](SECURITY.md) for more.

Detailed command reference: [docs/COMMANDS.md](docs/COMMANDS.md) (Simplified Chinese)  
Full tutorial: [docs/TUTORIAL.md](docs/TUTORIAL.md) (Simplified Chinese)

## Quick Build

Build online from PyPI:

```bash
cd make_ansible_portable
./build.sh --source ansible-core==2.15.13 --clean-output
```

`--clean-output` means: if `dist/` already contains an older bundle directory or archive with the same name, delete it first and rebuild. Without this flag, the command fails on name collisions so older artifacts are not overwritten by accident.

Important: the official PyPI package name for `2.10` is `ansible-base`, not `ansible-core`. For example, to build `2.10.17`, use `ansible-base==2.10.17`.

Build from a wheel you already downloaded:

```bash
./build.sh --source /path/to/ansible_core-2.15.13-py3-none-any.whl --clean-output
```

Build from an official sdist:

```bash
./build.sh --source /path/to/ansible-core-2.15.13.tar.gz --clean-output
```

By default the output goes to `dist/`:

- `dist/portable-ansible-core-2.15.13/`
- `dist/portable-ansible-core-2.15.13.tar.gz`

The default archive format is `gz`. You can switch it like this:

```bash
./build.sh --source ansible-core==2.15.13 --compression bz2 --clean-output
./build.sh --source ansible-core==2.15.13 --compression xz --clean-output
```

By default the build also copies this repository's `LICENSE`, `NOTICE`, `ACKNOWLEDGEMENTS.md`, and an `UPSTREAM-NOTICES.txt` file into the bundle root so redistributed artifacts keep their provenance and license notices.

## Run The Bundle

```bash
cd dist/portable-ansible-core-2.15.13
python3 ./ansible localhost -m ping
python3 ./ansible-playbook playbook.yml
python3 ./ansible-galaxy --version
```

## Control-Node Python vs Managed-Node Python

Do not mix these two concepts:

- Control-node Python: the Python interpreter used to run the portable bundle itself, for example `python3 ./ansible`.
- Managed-node Python: the Python interpreter used by Ansible modules on the remote machine after Ansible connects to it.

For `ansible-base 2.10`, the official `2.10` docs state:

- Control node: `Python 2.7` or `Python 3.5+`
- Managed node: `Python 2.6+` or `Python 3.5+`

If your portable bundle must run on a CentOS 7.5 control node that only has `Python 3.6`, you should build and self-test it with `Python 3.6`. That makes `pip` resolve dependency versions that are actually compatible with `Python 3.6`.

For `build.sh`, the two most important arguments are:

- `--source`: the official package version you want to bundle
- `--python`: the control-node Python the bundle will really run on

If you also need reproducible rebuilds, add a third one:

- `--build-constraint`: pin the runtime dependency set for reproducible builds

`--build-constraint` does not switch Python versions. It pins the runtime dependencies that end up in the bundle. For example, under `ansible-base 2.10.17` on `Python 3.6`, versions of `Jinja2`, `PyYAML`, `cryptography`, and similar packages can all be fixed by this file.

If you know you do not need `ansible-vault`, you can build with:

- `--without-vault`: remove the `ansible-vault` entrypoint and trim the `cryptography` / `cffi` runtime dependency chain for a smaller bundle

This is suitable when you do not use vault-encrypted files, vault-encrypted variables, or the `ansible-vault` CLI.  
Note: this does not remove `PyYAML`, because YAML parsing is part of normal Ansible execution, not only vault usage.

If you want to reduce bundle size further, you can also add:

- `--without-yaml-c-extension`: remove `yaml/_yaml*.so` and let `PyYAML` fall back to its pure-Python implementation

This usually saves the compiled `PyYAML` extension, but it is not the same kind of component as `cffi`. `_cffi_backend*.so` is not just an optional accelerator, so you should only remove that whole chain through `--without-vault`.

If the repository already contains a matching built-in lock file, `build.sh` now uses it automatically.  
For example, `ansible-base==2.10.17 + Python 3.6` automatically matches [locks/ansible-base-2.10.17-py36.txt](locks/ansible-base-2.10.17-py36.txt).

The tool supports explicitly selecting the Python used for the build:

```bash
./build.sh \
  --python /usr/bin/python3.6 \
  --source ansible-base==2.10.17 \
  --clean-output
```

If `--python` is lower than the minimum control-node Python version documented by Ansible for that release, the build fails immediately instead of waiting for confusing `pip` version filtering errors.

The human-maintained version map lives in [data/ansible_control_node_python.json](data/ansible_control_node_python.json). `build.sh` and `inspect-source` prefer this file, and package metadata `Requires-Python` is only used as a technical fallback.

The current toolchain also prepares an isolated build-tool environment automatically:

- it no longer depends on an old system `pip/setuptools/wheel`
- it prepares versions compatible with the Python selected by `--python`
- for `Python 3.6`, it automatically uses a compatible toolchain to avoid falling back to source builds for packages like `cryptography`
- only `Python 3.6` has an explicit compatibility pin today; for other Python versions the tool installs the newest `pip/setuptools/wheel` that still supports that interpreter

If you want to warm up or troubleshoot only that layer, run:

```bash
./prepare-build-python.sh --python /usr/bin/python3
```

The recommended day-to-day usage is therefore:

```bash
./build.sh \
  --python /usr/bin/python3 \
  --source ansible-base==2.10.17 \
  --clean-output
```

If your goal is the smallest possible `2.10.17` bundle and you know you do not need vault:

```bash
./build.sh \
  --python /usr/bin/python3.6 \
  --source ansible-base==2.10.17 \
  --without-vault \
  --without-yaml-c-extension \
  --clean-output
```

As long as your `python3` is `3.6.x` and the repository already contains the matching built-in lock file, the tool uses it automatically without requiring `--build-constraint`.

If you explicitly do not want the built-in lock file, add:

```bash
./build.sh \
  --python /usr/bin/python3 \
  --source ansible-base==2.10.17 \
  --no-auto-build-constraint \
  --clean-output
```

If you want to generate or update a lock file yourself, do it like this:

```bash
./freeze-build-lock.sh \
  --python /usr/bin/python3.6 \
  --source ansible-base==2.10.17

# Default output:
# ./locks/ansible-base-2.10.17-py36.txt

./build.sh \
  --python /usr/bin/python3.6 \
  --source ansible-base==2.10.17 \
  --build-constraint locks/ansible-base-2.10.17-py36.txt \
  --clean-output
```

You only need `--output` if you want to write the lock file somewhere else.

After the build, `portable-manifest.json` in the bundle root records:

- the Python path and version used for the build
- the final list of installed distributions and versions in the bundle

For example:

```bash
jq '.python,.installed_distributions' dist/portable-ansible-base-2.10.17/portable-manifest.json
```

## Inject Third-Party Python Packages

This section is about Python dependencies, not Ansible collections such as `ansible.posix`.

Inject them during the build:

```bash
./build.sh \
  --source ansible-core==2.15.13 \
  --extra-requirements examples/extras-mysql.txt \
  --extra-package requests
```

Or inject them after the bundle is built:

```bash
./install-extras.sh \
  --bundle dist/portable-ansible-core-2.15.13 \
  --extra-requirements examples/extras-k8s.txt
```

## Inject Ansible Collections

Content such as `ansible.posix` or `community.mysql` is an Ansible collection, not a Python package, so it is not installed into `ansible/extras/`.

The tool can install collections into `collections/` at the bundle root. When the portable bundle runs, that path is added automatically to both `ANSIBLE_COLLECTIONS_PATH` and `ANSIBLE_COLLECTIONS_PATHS`.

Important: the tool does not automatically choose the "last compatible collection version" based on `--python`, the managed-node `Python 2.7`, or an older `ansible-base` / `ansible-core` release. You still need to check `requires_ansible`, upstream release notes, and your real module/plugin usage.

For older environments such as `ansible-base 2.10.x`, the examples in this repository recommend explicitly pinning collection versions instead of installing `latest`.

Inject collections during the build:

```bash
./build.sh \
  --source ansible-base==2.10.17 \
  --extra-collection 'ansible.posix:==1.5.4'
```

Or use a requirements file:

```bash
./build.sh \
  --source ansible-core==2.15.13 \
  --extra-collection-requirements examples/collections-posix.yml
```

Or append collections after the bundle is built:

```bash
./install-collections.sh \
  --bundle dist/portable-ansible-base-2.10.17 \
  --extra-collection 'ansible.posix:==1.5.4'
```

After installation, verify them like this:

```bash
cd dist/portable-ansible-base-2.10.17
python3 ./ansible-galaxy collection list
python3 ./ansible-doc ansible.posix.synchronize
```

## Refresh The Tested Matrix

This command does four things automatically:

- query PyPI for the last patch release in each minor starting from `2.10`
- choose a matching Python interpreter according to `Requires-Python`
- run `./build.sh ... --skip-archive --clean-output` plus the automatic `localhost -m ping` self-test for each version
- rewrite the tested-version matrix in the README and write JSON results

If the required Python interpreters are already on `PATH`:

```bash
./refresh-tested-matrix.sh \
  --start-minor 2.10 \
  --python-candidate python3.9 \
  --python-candidate python3.10 \
  --python-candidate python3.11 \
  --python-candidate python3.12
```

If they are not on `PATH`, you can pass absolute paths directly:

```bash
./refresh-tested-matrix.sh \
  --start-minor 2.10 \
  --python-candidate /opt/python/3.9/bin/python3 \
  --python-candidate /opt/python/3.10/bin/python3 \
  --python-candidate /opt/python/3.11/bin/python3 \
  --python-candidate /opt/python/3.12/bin/python3
```

If you want to force one minor to use one specific interpreter:

```bash
./refresh-tested-matrix.sh \
  --start-minor 2.10 \
  --python-candidate python3.9 \
  --python-candidate python3.10 \
  --python-candidate python3.11 \
  --python-candidate python3.12 \
  --python-override 2.18=/opt/python/3.11/bin/python3
```

The JSON result is written to `dist-tests/tested-matrix.json` by default.

By default the command rewrites the English main README, `README.md`. If you also want to refresh the Chinese README, run it again with:

```bash
./refresh-tested-matrix.sh \
  --start-minor 2.10 \
  --python-candidate python3.9 \
  --python-candidate python3.10 \
  --python-candidate python3.11 \
  --python-candidate python3.12 \
  --readme README.zh-CN.md
```

The matrix language is chosen automatically from the `--readme` file name:

- `README.md`: English matrix
- `README.zh-CN.md`: Simplified Chinese matrix

## Tested Version Matrix

<!-- BEGIN TESTED MATRIX -->
Generated by `./refresh-tested-matrix.sh`.  
Test date: 2026-03-29

Test environment:

- `Python 3.9.25`: used for `2.10 to 2.15`
- `Python 3.10.20`: used for `2.16 to 2.17`
- `Python 3.11.15`: used for `2.18 to 2.19`
- `Python 3.12.13`: used for `2.20`

Pass criteria:

- `Passed`: `./build.sh --source <spec> --python <matching-python> --skip-archive --clean-output` succeeds
- and the automatic `localhost -m ping` self-test succeeds

Note: the official PyPI package name is still `ansible-base` for `2.10`; it changes to `ansible-core` starting from `2.11`.

| Minor | Package | Final patch | Status | Test Python | Requires-Python | Official downloads |
| --- | --- | --- | --- | --- | --- | --- |
| 2.10 | ansible-base | 2.10.17 | Passed | `3.9.25` | `>=2.7,!=3.0.*,!=3.1.*,!=3.2.*,!=3.3.*,!=3.4.*` | [PyPI](https://pypi.org/project/ansible-base/2.10.17/) · [sdist](https://files.pythonhosted.org/packages/fe/56/b18bf0167aa6e2ab195d0c2736992a3a9aeca1ddbefebee554226d211267/ansible-base-2.10.17.tar.gz) |
| 2.11 | ansible-core | 2.11.12 | Passed | `3.9.25` | `>=2.7,!=3.0.*,!=3.1.*,!=3.2.*,!=3.3.*,!=3.4.*` | [PyPI](https://pypi.org/project/ansible-core/2.11.12/) · [sdist](https://files.pythonhosted.org/packages/98/ea/2935bf0864196cd2c9d14548e399a110f48b3540664ddc462b39ff0b822d/ansible-core-2.11.12.tar.gz) |
| 2.12 | ansible-core | 2.12.10 | Passed | `3.9.25` | `>=3.8` | [PyPI](https://pypi.org/project/ansible-core/2.12.10/) · [sdist](https://files.pythonhosted.org/packages/e5/55/02da87b26d98a76a95bc8ef4df0ecff73cb73eb5b89ae5f2576b51785acb/ansible-core-2.12.10.tar.gz) |
| 2.13 | ansible-core | 2.13.13 | Passed | `3.9.25` | `>=3.8` | [PyPI](https://pypi.org/project/ansible-core/2.13.13/) · [sdist](https://files.pythonhosted.org/packages/33/ae/6a63fffda71543858ea0e0d78698d86e7cbdbd91b00b5335fa3f10031246/ansible-core-2.13.13.tar.gz) · [wheel](https://files.pythonhosted.org/packages/d2/c6/c5b0da259e583dbeaefdccdfe0a1e4fd7a342dba00e263183856290c7fc9/ansible_core-2.13.13-py3-none-any.whl) |
| 2.14 | ansible-core | 2.14.18 | Passed | `3.9.25` | `>=3.9` | [PyPI](https://pypi.org/project/ansible-core/2.14.18/) · [sdist](https://files.pythonhosted.org/packages/de/72/8a612ed5e13c376eebfc08a07994b66eb6d4fed98f368e828a191e06fa12/ansible_core-2.14.18.tar.gz) · [wheel](https://files.pythonhosted.org/packages/12/54/08580cf5131b81a5275d2b7db76de0fc210e05b5edd2ef78776f7dcfc2c1/ansible_core-2.14.18-py3-none-any.whl) |
| 2.15 | ansible-core | 2.15.13 | Passed | `3.9.25` | `>=3.9` | [PyPI](https://pypi.org/project/ansible-core/2.15.13/) · [sdist](https://files.pythonhosted.org/packages/69/dd/05343f635cb26df641c8366c5feb868ef5e2b893c625b04a6cb0cf1c7bfe/ansible_core-2.15.13.tar.gz) · [wheel](https://files.pythonhosted.org/packages/9b/2c/19ac50eca9d32a9524329f023a459ebb6ca5a546380eb15af384306c170a/ansible_core-2.15.13-py3-none-any.whl) |
| 2.16 | ansible-core | 2.16.18 | Passed | `3.10.20` | `>=3.10` | [PyPI](https://pypi.org/project/ansible-core/2.16.18/) · [sdist](https://files.pythonhosted.org/packages/b4/42/58905b3bc0cf46f2c55f376ff11a7b0cbf1b950778d3f29c1ec01eed1478/ansible_core-2.16.18.tar.gz) · [wheel](https://files.pythonhosted.org/packages/57/ef/172f73304928a7ebb16a86b3112d760c8e2033cb357d04762050b34d8870/ansible_core-2.16.18-py3-none-any.whl) |
| 2.17 | ansible-core | 2.17.14 | Passed | `3.10.20` | `>=3.10` | [PyPI](https://pypi.org/project/ansible-core/2.17.14/) · [sdist](https://files.pythonhosted.org/packages/ff/80/2925a0564f6f99a8002c3be3885b83c3a1dc5f57ebf00163f528889865f5/ansible_core-2.17.14.tar.gz) · [wheel](https://files.pythonhosted.org/packages/86/29/d694562f1a875b50aa74f691521fe493704f79cf1938cd58f28f7e2327d2/ansible_core-2.17.14-py3-none-any.whl) |
| 2.18 | ansible-core | 2.18.15 | Passed | `3.11.15` | `>=3.11` | [PyPI](https://pypi.org/project/ansible-core/2.18.15/) · [sdist](https://files.pythonhosted.org/packages/e4/82/a46d941447bd4add772482accc214a177a150346d14faaacf722a1190a88/ansible_core-2.18.15.tar.gz) · [wheel](https://files.pythonhosted.org/packages/14/98/396b04d1a76b03d47b9c8d1247230ac7094948ed2acfec9d2edc0ea76378/ansible_core-2.18.15-py3-none-any.whl) |
| 2.19 | ansible-core | 2.19.8 | Passed | `3.11.15` | `>=3.11` | [PyPI](https://pypi.org/project/ansible-core/2.19.8/) · [sdist](https://files.pythonhosted.org/packages/a9/cd/9dec1ad58657bcdf9759232db86bfe67006e0eb1c718775b89be0973554c/ansible_core-2.19.8.tar.gz) · [wheel](https://files.pythonhosted.org/packages/3d/2e/af15c35633d70c1ed1da800c61fe1824d3a2ce3c2e325548952617ef0469/ansible_core-2.19.8-py3-none-any.whl) |
| 2.20 | ansible-core | 2.20.4 | Passed | `3.12.13` | `>=3.12` | [PyPI](https://pypi.org/project/ansible-core/2.20.4/) · [sdist](https://files.pythonhosted.org/packages/11/7c/57263940ef61d7a829baef6e752556b1434f3a66ae05885c80753efbca50/ansible_core-2.20.4.tar.gz) · [wheel](https://files.pythonhosted.org/packages/71/19/fecf85f0f677405c0d4bec0c9f304b9f906f25599a176f4b16db7fa83571/ansible_core-2.20.4-py3-none-any.whl) |

Additional notes:

- The detailed JSON result from the most recent run is written to `dist-tests/tested-matrix.json`.
- If any row is not `Passed`, prepare a matching Python interpreter and rerun `./refresh-tested-matrix.sh`.
<!-- END TESTED MATRIX -->

## Inspect Official Package Dependencies

```bash
./inspect-source.sh --source ansible-core==2.15.13
./inspect-source.sh --source ansible-core==2.15.13 --json
```

## Repository Layout

- `build.sh`: main build entrypoint
- `install-extras.sh`: add third-party Python packages into an existing portable bundle
- `install-collections.sh`: add Ansible collections into an existing portable bundle
- `inspect-source.sh`: inspect official package metadata and runtime dependencies
- `freeze-build-lock.sh`: resolve and generate the main dependency lock file
- `refresh-tested-matrix.sh`: batch-test the last patch of each minor and refresh the README matrix
- `python/make_ansible_portable/`: Python implementation
- `templates/__main__.py`: portable launcher template
- `examples/`: example extras and collection inputs
- `locks/`: reproducible build constraints
- `docs/COMMANDS.md`: command reference (Simplified Chinese)
- `docs/TUTORIAL.md`: full tutorial (Simplified Chinese)

## License

- Repository code: `Apache-2.0`
- Packaging idea acknowledgement: `ownport/portable-ansible`
- Generated artifacts: follow the licenses of the included official Ansible packages and third-party dependencies
- `--strip-metadata` removes upstream `*.dist-info` / `*.egg-info` content and may remove license metadata too; only use it if you have already evaluated the licensing implications

## Release History

- Current latest version: `v0.3.0`
- First public version: `v0.1.0`
- Change history: [CHANGELOG.md](CHANGELOG.md)
- Security policy: [SECURITY.md](SECURITY.md)

## Full Tutorial

See [docs/TUTORIAL.md](docs/TUTORIAL.md) for the full tutorial in Simplified Chinese.
