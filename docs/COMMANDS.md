# 命令行参数参考

这个项目主要有 4 个入口脚本：

- `./build.sh`
- `./install-extras.sh`
- `./inspect-source.sh`
- `./freeze-build-lock.sh`
- `./prepare-build-python.sh`
- `./refresh-tested-matrix.sh`

你也可以直接执行 `--help` 查看当前版本的参数：

```bash
./build.sh --help
./install-extras.sh --help
./inspect-source.sh --help
./freeze-build-lock.sh --help
./prepare-build-python.sh --help
./refresh-tested-matrix.sh --help
```

## `build.sh`

用途：把官方 `ansible-base` / `ansible-core` 包打成便携目录和压缩包。

先记最重要的两个参数：

- `--source`: 你要打包的官方包版本
- `--python`: 这个便携包实际要跑在哪个控制机 Python 上

如果你还要求可复现，再加：

- `--build-constraint`: 把主运行依赖锁死

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
- `--build-constraint`: 主 Ansible/runtime 依赖安装时使用的 pip constraints 文件，用来实现可复现构建。
- `--no-auto-build-constraint`: 即使仓库 `locks/` 里有匹配当前 `--source + --python` 的内置锁文件，也不要自动使用。
- `--skip-archive`: 只生成目录，不生成 tar 包。
- `--skip-self-test`: 跳过 `localhost -m ping` 自测。
- `--strip-metadata`: 删除 `*.dist-info` 和 `*.egg-info`，减小体积，但也可能删掉上游许可证元数据。
- `--without-vault`: 删除 `ansible-vault` 入口，并裁掉 `cryptography` / `cffi` 运行时依赖链。生成的 bundle 不再支持 vault 加密文件、加密变量或 `ansible-vault` CLI。
- `--without-yaml-c-extension`: 删除 `yaml/_yaml*.so`，让 `PyYAML` 回退到纯 Python 解析/输出实现。
- `--python`: 指定构建和自测时使用的 Python 解释器。默认是当前 Python。如果它低于该 Ansible 版本在官方文档里声明的控制机最低 Python 版本，构建会直接失败。
- `--wheelhouse`: 指定本地 wheel 目录，构建时通过 `pip --find-links` 使用。
- `--offline`: 不访问 PyPI。通常要配合 `--wheelhouse` 或本地包文件使用。
- `--extra-package`: 在构建时顺便安装额外的 Python 包到 `ansible/extras`。可重复。
- `--extra-requirements`: 在构建时顺便安装 requirements 文件里的额外 Python 包。可重复。
- `--constraint`: extras 安装时使用的 pip constraints 文件。

关于 `--clean-output`：

- 它不是“随便清理临时目录”，而是专门清理当前这次构建对应的旧产物。
- 当前行为是：删除同名 bundle 目录，以及同名的 `tar.gz`、`tar.bz2`、`tar.xz` 旧包。
- 如果不加这个参数，而目标目录已经存在，构建会直接报错，避免误覆盖旧产物。

关于 `2.10`：

- `2.10` 这一代在 PyPI 上的官方包名是 `ansible-base`。
- 从 `2.11` 开始，官方包名才是 `ansible-core`。
- 也就是说，`2.10.17` 要写成 `ansible-base==2.10.17`。

关于“自动准备构建工具”：

- `build.sh` 现在会先自动准备一个隔离的 `pip/setuptools/wheel` 环境，再用它去下载和安装依赖。
- 这一步按 `--python` 选择兼容版本，不再要求你手工记“CentOS 7.5 + Python 3.6 该装哪个 pip”。
- 对 `Python 3.6`，它会自动避开过新的 `pip/setuptools`，从而正确识别 wheel，避免 `cryptography` 走源码编译。
- 目前只有 `Python 3.6` 做了显式兼容固定；其他 Python 版本默认安装该解释器还能用的最新 `pip/setuptools/wheel`。

关于 `--build-constraint`：

- 这个参数是“锁版本”，不是“选 Python”。
- 它约束的是主运行依赖，例如 `Jinja2`、`PyYAML`、`cryptography`、`packaging`。
- 不加时：每次构建都会解析“当前仍兼容 `--python` 的最新版本”。
- 加上时：会尽量固定成同一组版本，适合做可复现发布。

关于“内置锁文件自动匹配”：

- `build.sh` 现在会优先按 `包名 + 版本 + Python 主次版本` 去 `locks/` 目录里找内置锁文件。
- 例如：`ansible-base==2.10.17` + `Python 3.6` 会自动匹配 `locks/ansible-base-2.10.17-py36.txt`。
- 所以常见情况下，你不需要手工写 `--build-constraint`。
- 只有你想覆盖默认锁文件，才显式传 `--build-constraint`。
- 如果你想彻底禁用这层自动匹配，就传 `--no-auto-build-constraint`。

关于 `--without-vault`：

- 它是“安装完成后按特性裁剪”，不是改官方依赖解析规则。
- 当前会移除 `cryptography`、`cffi`、`_cffi_backend*.so`，以及这条依赖链带进来的 `pycparser`、`typing_extensions`，并且不再生成 `ansible-vault` 命令入口。
- 它不会裁掉 `PyYAML`。Ansible 的配置、inventory、playbook、collection 元数据等常规路径都需要 YAML 解析。

关于 `--without-yaml-c-extension`：

- 它只移除 `PyYAML` 的 LibYAML C 扩展共享库 `yaml/_yaml*.so`。
- 删除后，`PyYAML` 会自动回退到纯 Python 实现，功能还在，只是 YAML 解析/输出速度会慢一些。
- 它和 `_cffi_backend*.so` 不是同一类东西。后者不是“纯加速器”，只要还保留 `cryptography/cffi`，就不能单独删。

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

这个命令的文本输出现在会优先显示“官方控制机最低 Python 版本”和官方文档链接，而不是直接把原始 `Requires-Python` 字符串抛给你。

这份映射表维护在 [data/ansible_control_node_python.json](/usr/local/make_ansible_portable/data/ansible_control_node_python.json)。

## `freeze-build-lock.sh`

用途：解析某个 Ansible 版本在指定控制机 Python 下最终会安装哪些包，并把结果写成一个 constraints 文件，后续 `build.sh` 可直接复用。

常见用法：

```bash
./freeze-build-lock.sh \
  --python /usr/bin/python3.6 \
  --source ansible-base==2.10.17
```

默认输出到：

```bash
locks/ansible-base-2.10.17-py36.txt
```

参数说明：

- `--source`: 必填。官方包来源。
- `--output`: 可选。输出锁文件路径。不写时默认按 `./locks/<package>-<version>-pyXY.txt` 生成。
- `--build-constraint`: 可选。允许在已有约束基础上继续解析。
- `--python`: 指定控制机 Python。这个参数最关键。
- `--wheelhouse`: 指定本地 wheel 目录。
- `--offline`: 不访问 PyPI。通常要配合 `--wheelhouse` 或本地包文件使用。

## `prepare-build-python.sh`

用途：提前准备构建过程中使用的隔离 `pip/setuptools/wheel` 环境。

常见用法：

```bash
./prepare-build-python.sh --python /usr/bin/python3
```

参数说明：

- `--python`: 必填语义上最重要。指定要为哪个控制机 Python 准备构建工具。
- `--wheelhouse`: 可选。离线或半离线准备时使用本地 wheel 仓库。
- `--offline`: 不访问 PyPI。通常要配合 `--wheelhouse`。

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

## 控制机 Python vs 目标机 Python

这里有两个经常混淆的概念：

- 控制机 Python：运行便携包的 Python，也就是 `python3 ./ansible` 使用的那个 Python。
- 目标机 Python：Ansible 连上远程主机后，远程模块在目标机上使用的 Python。

`--python` 影响的是控制机这一侧：

- 它决定 `pip` 解析依赖时按照哪个 Python 版本选包
- 它也决定构建后的 `localhost -m ping` 自测使用哪个 Python

如果你希望便携包在只有 `Python 3.6` 的控制机上运行，就应该用 `--python /path/to/python3.6` 来构建。

构建完成后，可以直接看 bundle 根目录下的 `portable-manifest.json`：

- `.python`：构建时使用的控制机 Python
- `.installed_distributions`：实际安装进 bundle 的包和版本

如果你想把这一组依赖固定下来，先跑一次 `./freeze-build-lock.sh`，再把生成的文件通过 `--build-constraint` 传给 `./build.sh`。
