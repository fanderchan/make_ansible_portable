# make_ansible_portable

把官方 `ansible-base` / `ansible-core` 包做成“解压即用”的便携式 Ansible。

核心思路和 `portable-ansible` 类似：

- 不改官方 Ansible 运行时代码
- 用 `pip --target` 把官方包直接安装到一个目录
- 在目录里放一个自定义 `__main__.py`
- 通过 `python3 ./ansible` 或 `python3 ./ansible-playbook` 运行
- 第三方 Python 包统一装进 `ansible/extras`

## 开源说明

- 这个项目的整体打包思路参考并致敬了 [`ownport/portable-ansible`](https://github.com/ownport/portable-ansible)。
- 当前 [`templates/__main__.py`](templates/__main__.py) 是为本仓库重写的独立 launcher，实现的是同类思路，不再沿用上游文件头或源码文本。
- 仓库代码使用 `Apache-2.0` 发布。
- 本项目与 Ansible 项目、Red Hat、`ownport/portable-ansible` 没有关联，也不代表它们的官方立场。
- 生成出的便携包会包含官方 Ansible 包和其依赖。你在分发这些产物时，还需要遵守它们各自的许可证。

更多说明见 [LICENSE](LICENSE)、[NOTICE](NOTICE)、[ACKNOWLEDGEMENTS.md](ACKNOWLEDGEMENTS.md)、[CONTRIBUTING.md](CONTRIBUTING.md)、[CHANGELOG.md](CHANGELOG.md) 和 [SECURITY.md](SECURITY.md)。

命令行参数总表见 [docs/COMMANDS.md](docs/COMMANDS.md)。

## 一键构建

在线从 PyPI 构建：

```bash
cd make_ansible_portable
./build.sh --source ansible-core==2.15.13 --clean-output
```

`--clean-output` 的意思是：如果 `dist/` 里已经有同名的旧目录或旧压缩包，就先删掉再重建；不加这个参数时，遇到同名旧产物会直接报错，避免误覆盖。

注意：`2.10` 这一代官方 PyPI 包名是 `ansible-base`，不是 `ansible-core`。例如要打 `2.10.17`，应使用 `ansible-base==2.10.17`。

从你已经下载好的官方 wheel 构建：

```bash
./build.sh --source /path/to/ansible_core-2.15.13-py3-none-any.whl --clean-output
```

从官方 sdist 构建：

```bash
./build.sh --source /path/to/ansible-core-2.15.13.tar.gz --clean-output
```

构建完成后，默认输出在 `dist/`：

- `dist/portable-ansible-core-2.15.13/`
- `dist/portable-ansible-core-2.15.13.tar.gz`

默认压缩格式是 `gz`。如果你想切换：

```bash
./build.sh --source ansible-core==2.15.13 --compression bz2 --clean-output
./build.sh --source ansible-core==2.15.13 --compression xz --clean-output
```

默认构建还会把仓库的 `LICENSE`、`NOTICE`、`ACKNOWLEDGEMENTS.md` 和一个
`UPSTREAM-NOTICES.txt` 写进便携包根目录，方便你在分发 bundle 时保留
来源和许可证说明。

## 运行便携包

```bash
cd dist/portable-ansible-core-2.15.13
python3 ./ansible localhost -m ping
python3 ./ansible-playbook playbook.yml
python3 ./ansible-galaxy --version
```

## 控制机 Python 和目标机 Python

这两个概念不要混在一起：

- 控制机 Python：运行这个便携包的 Python。也就是你执行 `python3 ./ansible` 时用的那个 Python。
- 目标机 Python：Ansible 连接远程主机后，远程模块实际使用的 Python。

对 `ansible-base 2.10`，官方 `2.10` 文档说明：

- 控制机支持 `Python 2.7` 或 `Python 3.5+`
- 目标机支持 `Python 2.6+` 或 `Python 3.5+`

如果你的便携包要跑在 CentOS 7.5 控制机上，并且那台控制机只有 `Python 3.6`，那你就应该用 `Python 3.6` 来构建和自测，这样 `pip` 才会解析出与 `Python 3.6` 兼容的依赖版本。

对 `build.sh` 来说，最重要的两个参数就是：

- `--source`：你要打包的官方包版本
- `--python`：这个便携包实际要跑在哪个控制机 Python 上

如果你还要求“下一次重打仍然是同一组依赖版本”，就再加第三个参数：

- `--build-constraint`：把依赖锁死，做成可复现构建

`--build-constraint` 的作用不是“切换 Python”，而是锁住主运行依赖版本。比如 `ansible-base 2.10.17` 在 `Python 3.6` 下，实际会装进 bundle 的 `Jinja2`、`PyYAML`、`cryptography` 等版本，都可以通过这个文件固定下来。

如果你明确不需要 `ansible-vault`，还可以在构建时加：

- `--without-vault`：删除便携包里的 `ansible-vault` 入口，并裁掉 `cryptography` / `cffi` 运行时依赖链，换更小体积

这个选项适合“不使用 vault 加密文件、加密变量、ansible-vault CLI”的场景。  
注意：它不会裁掉 `PyYAML`，因为 YAML 解析是 Ansible 常规运行路径，不只是 vault 在用。

如果你还想进一步减小体积，可以再加：

- `--without-yaml-c-extension`：不打 `yaml/_yaml*.so`，让 `PyYAML` 回退到纯 Python 实现

这个选项通常能再省掉一份 `PyYAML` 的编译版 `.so`。  
但它和 `cffi` 不是同一类事情：`_cffi_backend*.so` 不是纯加速器，只有配合 `--without-vault` 一起去掉整条依赖链才安全。

如果仓库里已经有匹配的内置锁文件，`build.sh` 现在默认会自动使用它。  
例如：`ansible-base==2.10.17 + Python 3.6` 会自动匹配 [locks/ansible-base-2.10.17-py36.txt](/usr/local/make_ansible_portable/locks/ansible-base-2.10.17-py36.txt)。

当前工具支持指定构建使用的 Python：

```bash
./build.sh \
  --python /usr/bin/python3.6 \
  --source ansible-base==2.10.17 \
  --clean-output
```

如果 `--python` 低于该版本在官方文档里声明的控制机最低 Python 版本，构建会直接失败，而不是等 `pip` 打出一大串难读的版本过滤错误。

这份人类可读的版本映射表维护在 [data/ansible_control_node_python.json](/usr/local/make_ansible_portable/data/ansible_control_node_python.json)，构建和 `inspect-source` 会优先读取它；包自身的 `Requires-Python` 只作为技术性兜底。

从当前版本开始，工具还会自动为你准备一个“隔离的构建工具环境”：

- 默认不再依赖系统里旧的 `pip/setuptools/wheel`
- 会按你传入的 `--python` 自动准备兼容版本
- 对 `Python 3.6`，会自动使用兼容组合，避免 `cryptography` 退回源码编译
- 目前只有 `Python 3.6` 做了显式兼容固定；其他 Python 版本默认安装该解释器还能用的最新 `pip/setuptools/wheel`

如果你想单独预热或排查这一层，可以执行：

```bash
./prepare-build-python.sh --python /usr/bin/python3
```

所以更推荐的日常用法其实是：

```bash
./build.sh \
  --python /usr/bin/python3 \
  --source ansible-base==2.10.17 \
  --clean-output
```

如果你的目标是尽量减小 `2.10.17` 绿色包体积，并且确认不需要 vault：

```bash
./build.sh \
  --python /usr/bin/python3.6 \
  --source ansible-base==2.10.17 \
  --without-vault \
  --without-yaml-c-extension \
  --clean-output
```

只要你的 `python3` 是 `3.6.x`，并且仓库里已经有对应内置锁文件，工具就会自动应用，不需要你手工再写 `--build-constraint`。

如果你明确不想用内置锁文件，才加：

```bash
./build.sh \
  --python /usr/bin/python3 \
  --source ansible-base==2.10.17 \
  --no-auto-build-constraint \
  --clean-output
```

如果你想自己生成或更新锁文件，再这样做：

```bash
./freeze-build-lock.sh \
  --python /usr/bin/python3.6 \
  --source ansible-base==2.10.17

# 默认会生成到:
# ./locks/ansible-base-2.10.17-py36.txt

./build.sh \
  --python /usr/bin/python3.6 \
  --source ansible-base==2.10.17 \
  --build-constraint locks/ansible-base-2.10.17-py36.txt \
  --clean-output
```

只有你想把锁文件输出到别的位置，才额外传 `--output`。

构建完成后，便携包根目录的 `portable-manifest.json` 会记录：

- 构建时使用的 Python 路径和版本
- 最终装进 bundle 的分发包列表和版本

例如：

```bash
jq '.python,.installed_distributions' dist/portable-ansible-base-2.10.17/portable-manifest.json
```

## 第三方 Python 包注入

构建时直接打进去：

```bash
./build.sh \
  --source ansible-core==2.15.13 \
  --extra-requirements examples/extras-mysql.txt \
  --extra-package requests
```

构建后再打进去：

```bash
./install-extras.sh \
  --bundle dist/portable-ansible-core-2.15.13 \
  --extra-requirements examples/extras-k8s.txt
```

## 一键刷新测试矩阵

这个命令会自动做四件事：

- 查询 PyPI 上从 `2.10` 开始每个 minor 的最后一个小版本
- 按 `Requires-Python` 自动选择匹配的 Python 解释器
- 对每个版本执行 `./build.sh ... --skip-archive --clean-output` 和 `localhost -m ping` 自测
- 重写本 README 里的“已测试版本矩阵”，并输出 JSON 结果

如果你的高版本 Python 已经在 `PATH` 里：

```bash
./refresh-tested-matrix.sh \
  --start-minor 2.10 \
  --python-candidate python3.9 \
  --python-candidate python3.10 \
  --python-candidate python3.11 \
  --python-candidate python3.12
```

如果解释器不在 `PATH`，也可以直接给绝对路径：

```bash
./refresh-tested-matrix.sh \
  --start-minor 2.10 \
  --python-candidate /opt/python/3.9/bin/python3 \
  --python-candidate /opt/python/3.10/bin/python3 \
  --python-candidate /opt/python/3.11/bin/python3 \
  --python-candidate /opt/python/3.12/bin/python3
```

如果你想强制某个 minor 用某个解释器：

```bash
./refresh-tested-matrix.sh \
  --start-minor 2.10 \
  --python-candidate python3.9 \
  --python-candidate python3.10 \
  --python-candidate python3.11 \
  --python-candidate python3.12 \
  --python-override 2.18=/opt/python/3.11/bin/python3
```

默认结果会写到 `dist-tests/tested-matrix.json`。

## 已测试版本矩阵

<!-- BEGIN TESTED MATRIX -->
这段内容由 `./refresh-tested-matrix.sh` 自动生成。  
测试时间：2026-03-29

测试环境：

- `Python 3.9.25`：用于 `2.10 到 2.15`
- `Python 3.10.20`：用于 `2.16 到 2.17`
- `Python 3.11.15`：用于 `2.18 到 2.19`
- `Python 3.12.13`：用于 `2.20`

判定标准：

- `已测通过`：`./build.sh --source <spec> --python <matching-python> --skip-archive --clean-output` 成功
- 并且自动 `localhost -m ping` 自测成功

说明：`2.10` 这一代官方包名还是 `ansible-base`，从 `2.11` 起才是 `ansible-core`。

| Minor | Package | Final patch | 状态 | 测试 Python | Requires-Python | 官方下载 |
| --- | --- | --- | --- | --- | --- | --- |
| 2.10 | ansible-base | 2.10.17 | 已测通过 | `3.9.25` | `>=2.7,!=3.0.*,!=3.1.*,!=3.2.*,!=3.3.*,!=3.4.*` | [PyPI](https://pypi.org/project/ansible-base/2.10.17/) · [sdist](https://files.pythonhosted.org/packages/fe/56/b18bf0167aa6e2ab195d0c2736992a3a9aeca1ddbefebee554226d211267/ansible-base-2.10.17.tar.gz) |
| 2.11 | ansible-core | 2.11.12 | 已测通过 | `3.9.25` | `>=2.7,!=3.0.*,!=3.1.*,!=3.2.*,!=3.3.*,!=3.4.*` | [PyPI](https://pypi.org/project/ansible-core/2.11.12/) · [sdist](https://files.pythonhosted.org/packages/98/ea/2935bf0864196cd2c9d14548e399a110f48b3540664ddc462b39ff0b822d/ansible-core-2.11.12.tar.gz) |
| 2.12 | ansible-core | 2.12.10 | 已测通过 | `3.9.25` | `>=3.8` | [PyPI](https://pypi.org/project/ansible-core/2.12.10/) · [sdist](https://files.pythonhosted.org/packages/e5/55/02da87b26d98a76a95bc8ef4df0ecff73cb73eb5b89ae5f2576b51785acb/ansible-core-2.12.10.tar.gz) |
| 2.13 | ansible-core | 2.13.13 | 已测通过 | `3.9.25` | `>=3.8` | [PyPI](https://pypi.org/project/ansible-core/2.13.13/) · [sdist](https://files.pythonhosted.org/packages/33/ae/6a63fffda71543858ea0e0d78698d86e7cbdbd91b00b5335fa3f10031246/ansible-core-2.13.13.tar.gz) · [wheel](https://files.pythonhosted.org/packages/d2/c6/c5b0da259e583dbeaefdccdfe0a1e4fd7a342dba00e263183856290c7fc9/ansible_core-2.13.13-py3-none-any.whl) |
| 2.14 | ansible-core | 2.14.18 | 已测通过 | `3.9.25` | `>=3.9` | [PyPI](https://pypi.org/project/ansible-core/2.14.18/) · [sdist](https://files.pythonhosted.org/packages/de/72/8a612ed5e13c376eebfc08a07994b66eb6d4fed98f368e828a191e06fa12/ansible_core-2.14.18.tar.gz) · [wheel](https://files.pythonhosted.org/packages/12/54/08580cf5131b81a5275d2b7db76de0fc210e05b5edd2ef78776f7dcfc2c1/ansible_core-2.14.18-py3-none-any.whl) |
| 2.15 | ansible-core | 2.15.13 | 已测通过 | `3.9.25` | `>=3.9` | [PyPI](https://pypi.org/project/ansible-core/2.15.13/) · [sdist](https://files.pythonhosted.org/packages/69/dd/05343f635cb26df641c8366c5feb868ef5e2b893c625b04a6cb0cf1c7bfe/ansible_core-2.15.13.tar.gz) · [wheel](https://files.pythonhosted.org/packages/9b/2c/19ac50eca9d32a9524329f023a459ebb6ca5a546380eb15af384306c170a/ansible_core-2.15.13-py3-none-any.whl) |
| 2.16 | ansible-core | 2.16.18 | 已测通过 | `3.10.20` | `>=3.10` | [PyPI](https://pypi.org/project/ansible-core/2.16.18/) · [sdist](https://files.pythonhosted.org/packages/b4/42/58905b3bc0cf46f2c55f376ff11a7b0cbf1b950778d3f29c1ec01eed1478/ansible_core-2.16.18.tar.gz) · [wheel](https://files.pythonhosted.org/packages/57/ef/172f73304928a7ebb16a86b3112d760c8e2033cb357d04762050b34d8870/ansible_core-2.16.18-py3-none-any.whl) |
| 2.17 | ansible-core | 2.17.14 | 已测通过 | `3.10.20` | `>=3.10` | [PyPI](https://pypi.org/project/ansible-core/2.17.14/) · [sdist](https://files.pythonhosted.org/packages/ff/80/2925a0564f6f99a8002c3be3885b83c3a1dc5f57ebf00163f528889865f5/ansible_core-2.17.14.tar.gz) · [wheel](https://files.pythonhosted.org/packages/86/29/d694562f1a875b50aa74f691521fe493704f79cf1938cd58f28f7e2327d2/ansible_core-2.17.14-py3-none-any.whl) |
| 2.18 | ansible-core | 2.18.15 | 已测通过 | `3.11.15` | `>=3.11` | [PyPI](https://pypi.org/project/ansible-core/2.18.15/) · [sdist](https://files.pythonhosted.org/packages/e4/82/a46d941447bd4add772482accc214a177a150346d14faaacf722a1190a88/ansible_core-2.18.15.tar.gz) · [wheel](https://files.pythonhosted.org/packages/14/98/396b04d1a76b03d47b9c8d1247230ac7094948ed2acfec9d2edc0ea76378/ansible_core-2.18.15-py3-none-any.whl) |
| 2.19 | ansible-core | 2.19.8 | 已测通过 | `3.11.15` | `>=3.11` | [PyPI](https://pypi.org/project/ansible-core/2.19.8/) · [sdist](https://files.pythonhosted.org/packages/a9/cd/9dec1ad58657bcdf9759232db86bfe67006e0eb1c718775b89be0973554c/ansible_core-2.19.8.tar.gz) · [wheel](https://files.pythonhosted.org/packages/3d/2e/af15c35633d70c1ed1da800c61fe1824d3a2ce3c2e325548952617ef0469/ansible_core-2.19.8-py3-none-any.whl) |
| 2.20 | ansible-core | 2.20.4 | 已测通过 | `3.12.13` | `>=3.12` | [PyPI](https://pypi.org/project/ansible-core/2.20.4/) · [sdist](https://files.pythonhosted.org/packages/11/7c/57263940ef61d7a829baef6e752556b1434f3a66ae05885c80753efbca50/ansible_core-2.20.4.tar.gz) · [wheel](https://files.pythonhosted.org/packages/71/19/fecf85f0f677405c0d4bec0c9f304b9f906f25599a176f4b16db7fa83571/ansible_core-2.20.4-py3-none-any.whl) |

补充说明：

- 最近一次执行的详细 JSON 结果会写到 `dist-tests/tested-matrix.json`。
- 如果某一行不是 `已测通过`，准备好匹配的 Python 解释器后重新执行 `./refresh-tested-matrix.sh`。
<!-- END TESTED MATRIX -->

## 查看官方包依赖

```bash
./inspect-source.sh --source ansible-core==2.15.13
./inspect-source.sh --source ansible-core==2.15.13 --json
```

## 目录说明

- `build.sh`: 主构建入口
- `install-extras.sh`: 给已构建便携包追加第三方 Python 包
- `inspect-source.sh`: 读取官方包元数据和运行时依赖
- `freeze-build-lock.sh`: 解析并生成主依赖锁文件
- `refresh-tested-matrix.sh`: 批量测试每个 minor 的末版并刷新 README 矩阵
- `python/make_ansible_portable/`: Python 实现
- `templates/__main__.py`: 便携入口模板
- `examples/`: 常见 extras 示例
- `locks/`: 可复现构建用的约束文件示例
- `docs/COMMANDS.md`: 命令行参数参考
- `docs/TUTORIAL.md`: 完整教程

## 许可证

- 仓库代码：`Apache-2.0`
- 思路致谢：`ownport/portable-ansible`
- 生成产物：遵循其中包含的官方 Ansible 和第三方依赖各自许可证
- `--strip-metadata` 会删掉上游包的 `*.dist-info` / `*.egg-info`，可能同时删掉许可证元数据。这个选项只适合你明确评估过许可证影响的场景

## 发布记录

- 首个公开版本：`v0.1.0`
- 变更记录见 [CHANGELOG.md](CHANGELOG.md)
- 安全说明见 [SECURITY.md](SECURITY.md)

## 完整教程

见 [docs/TUTORIAL.md](docs/TUTORIAL.md)。
