# 命令行参数参考

这个项目主要有 4 个入口脚本：

- `./build.sh`
- `./install-extras.sh`
- `./inspect-source.sh`
- `./refresh-tested-matrix.sh`

你也可以直接执行 `--help` 查看当前版本的参数：

```bash
./build.sh --help
./install-extras.sh --help
./inspect-source.sh --help
./refresh-tested-matrix.sh --help
```

## `build.sh`

用途：把官方 `ansible-base` / `ansible-core` 包打成便携目录和压缩包。

常见用法：

```bash
./build.sh --source ansible-core==2.15.13 --clean-output
```

参数说明：

- `--source`: 必填。官方包来源，可以是 PyPI 规格、本地 wheel、或本地 sdist。
- `--bundle-name`: 自定义输出目录名。默认是 `portable-<package>-<version>`。
- `--output-dir`: 输出目录。默认是 `dist/`。
- `--compression`: 压缩格式，可选 `gz`、`bz2`、`xz`。默认是 `gz`。
- `--clean-output`: 如果输出目录里已经存在同名 bundle 目录，或者存在同名的旧压缩包，就先删除再重建。
- `--skip-archive`: 只生成目录，不生成 tar 包。
- `--skip-self-test`: 跳过 `localhost -m ping` 自测。
- `--strip-metadata`: 删除 `*.dist-info` 和 `*.egg-info`，减小体积，但也可能删掉上游许可证元数据。
- `--python`: 指定构建和自测时使用的 Python 解释器。默认是当前 Python。
- `--wheelhouse`: 指定本地 wheel 目录，构建时通过 `pip --find-links` 使用。
- `--offline`: 不访问 PyPI。通常要配合 `--wheelhouse` 或本地包文件使用。
- `--extra-package`: 在构建时顺便安装额外的 Python 包到 `ansible/extras`。可重复。
- `--extra-requirements`: 在构建时顺便安装 requirements 文件里的额外 Python 包。可重复。
- `--constraint`: extras 安装时使用的 pip constraints 文件。

关于 `--clean-output`：

- 它不是“随便清理临时目录”，而是专门清理当前这次构建对应的旧产物。
- 当前行为是：删除同名 bundle 目录，以及同名的 `tar.gz`、`tar.bz2`、`tar.xz` 旧包。
- 如果不加这个参数，而目标目录已经存在，构建会直接报错，避免误覆盖旧产物。

## `install-extras.sh`

用途：对已经生成的便携包，追加安装第三方 Python 包到 `ansible/extras`。

常见用法：

```bash
./install-extras.sh \
  --bundle dist/portable-ansible-core-2.15.13 \
  --extra-requirements examples/extras-mysql.txt
```

参数说明：

- `--bundle`: 必填。已解压便携包目录。
- `--self-test`: extras 安装完成后，自动跑一次 `localhost -m ping`。
- `--python`: 指定安装 extras 和自测时使用的 Python 解释器。
- `--wheelhouse`: 指定本地 wheel 目录。
- `--offline`: 不访问 PyPI。通常要配合 `--wheelhouse` 或本地包文件使用。
- `--extra-package`: 追加安装单个 Python 包。可重复。
- `--extra-requirements`: 追加安装 requirements 文件。可重复。
- `--constraint`: extras 安装时使用的 pip constraints 文件。

## `inspect-source.sh`

用途：读取官方包元数据，查看版本、制品路径、运行时依赖。

常见用法：

```bash
./inspect-source.sh --source ansible-core==2.15.13
./inspect-source.sh --source ansible-core==2.15.13 --json
```

参数说明：

- `--source`: 必填。官方包来源，可以是 PyPI 规格或本地 wheel / sdist。
- `--json`: 以 JSON 输出完整元数据。
- `--python`: 指定解析和下载时使用的 Python 解释器。
- `--wheelhouse`: 指定本地 wheel 目录。
- `--offline`: 不访问 PyPI。通常要配合 `--wheelhouse` 或本地包文件使用。

## `refresh-tested-matrix.sh`

用途：从 `2.10` 开始批量测试每个 minor 的最后一个小版本，并刷新 README 里的测试矩阵。

常见用法：

```bash
./refresh-tested-matrix.sh \
  --start-minor 2.10 \
  --python-candidate python3.9 \
  --python-candidate python3.10 \
  --python-candidate python3.11 \
  --python-candidate python3.12
```

参数说明：

- `--start-minor`: 起始 minor。默认是 `2.10`。
- `--end-minor`: 可选结束 minor。不写时自动测到 PyPI 当前最新稳定 minor。
- `--readme`: 要被重写测试矩阵的 README 文件。默认是 `README.md`。
- `--output-dir`: 批量测试过程中临时 bundle 的输出目录。默认是 `dist-tests/`。
- `--results-json`: JSON 结果输出路径。默认是 `<output-dir>/tested-matrix.json`。
- `--python-candidate`: 候选 Python 解释器。可重复。
- `--python-override`: 为某个 minor 强制指定解释器。格式是 `2.18=/path/to/python`。可重复。
- `--skip-readme-update`: 只写 JSON，不修改 README。
- `--wheelhouse`: 指定本地 wheel 目录。
- `--offline`: 构建测试 bundle 时不访问 PyPI 包下载。PyPI 版本元数据仍需要查询。

## 建议先记住的几个参数

如果你平时只会用到一小部分参数，先记这几个就够了：

- `--source`: 指定要打包的官方包
- `--clean-output`: 先删同名旧产物再重建
- `--compression`: 选择 `gz`、`bz2`、`xz`
- `--skip-archive`: 只要目录，不要 tar 包
- `--python`: 切换构建使用的 Python
- `--extra-package` / `--extra-requirements`: 把第三方 Python 包打进 `extras`
- `--offline` / `--wheelhouse`: 离线或半离线构建
