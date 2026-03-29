# 完整教程

## 1. 这个项目做了什么

这个工具把官方 `ansible-core` 包打进一个目录，再放入一个自定义 `__main__.py` 作为便携入口。

结果是：

- 不需要先 `pip install ansible-core`
- 不需要 virtualenv
- 只要目标机器有兼容的 `python3`
- 解压后直接 `python3 ./ansible` 即可运行

注意：

- 这是“便携 Python 目录”，不是带 Python 解释器的单文件程序
- 目标机器仍然需要有兼容版本的 `python3`

## 2. 准备条件

建议本机具备：

- `python3`
- `pip`
- 能访问 PyPI，或者你已经准备好官方 wheel/sdist

查看当前 Python：

```bash
python3 --version
```

## 2.1 先分清两个 Python

这里一定要分清：

- 控制机 Python：运行便携版 Ansible 的 Python
- 目标机 Python：远程主机执行 Ansible 模块时使用的 Python

对 `ansible-base 2.10`，官方 `2.10` 安装文档写的是：

- 控制机：`Python 2.7` 或 `Python 3.5+`
- 目标机：`Python 2.6+` 或 `Python 3.5+`

所以如果你的目标是：

- 便携包要运行在 CentOS 7.5 控制机上
- 而那台控制机只有 `Python 3.6`

那你就应该用 `Python 3.6` 来构建。原因很简单：当前工具会用你指定的 Python 去做 `pip install` 和自测，依赖版本会跟着那个 Python 的兼容范围来选。

构建前用于判断“这个版本最低该用什么控制机 Python”的映射表，维护在 [data/ansible_control_node_python.json](/usr/local/make_ansible_portable/data/ansible_control_node_python.json)。这份表是按 Ansible 官方文档整理出来的，用户输出优先读它，不再直接展示难看的 `Requires-Python` 原始字符串。

对 `build.sh` 来说，最关键的两个参数就是：

- `--source`：你要打包的官方包版本
- `--python`：这个便携包实际要跑在哪个控制机 Python 上

如果你还要求可复现，就再加第三个参数：

- `--build-constraint`：把当时解析出来的主运行依赖固定下来

这里要特别分清：

- `--python`：决定控制机 Python，也决定依赖解析的兼容范围
- `--build-constraint`：决定是否把最终解析出来的依赖版本锁住

例如 `ansible-base 2.10.17` 在 `Python 3.6` 下，真正会装进 bundle 的 `Jinja2`、`PyYAML`、`cryptography` 等版本，都属于 `--build-constraint` 管的范围。

例子：

```bash
./build.sh \
  --python /usr/bin/python3.6 \
  --source ansible-base==2.10.17 \
  --clean-output
```

从当前版本开始，`build.sh` 还会自动先准备一个隔离的构建工具环境：

- 自动准备兼容的 `pip/setuptools/wheel`
- 不再依赖系统自带的老 `pip`
- 对 CentOS 7.5 这种 `Python 3.6 + pip 9` 的机器，能自动规避 `cryptography` 退回源码编译的问题

如果你想先单独做这一层准备，可以执行：

```bash
./prepare-build-python.sh --python /usr/bin/python3.6
```

如果你还想把依赖版本锁住，让以后重打时结果不漂移，建议改成两步：

```bash
./freeze-build-lock.sh \
  --python /usr/bin/python3.6 \
  --source ansible-base==2.10.17 \
  --output locks/ansible-base-2.10.17-py36.txt

./build.sh \
  --python /usr/bin/python3.6 \
  --source ansible-base==2.10.17 \
  --build-constraint locks/ansible-base-2.10.17-py36.txt \
  --clean-output
```

构建完成后，可以查看：

```bash
jq '.python,.installed_distributions' dist/portable-ansible-base-2.10.17/portable-manifest.json
```

这样你就能确认：

- 构建到底用了哪个 Python
- 最终装进去了哪些依赖和版本

如果你希望下一次构建还是完全同一组版本，就不要只看 manifest，要把 `freeze-build-lock.sh` 生成的锁文件一起保存下来。

## 3. 最简单的一键构建

完整参数表见 [docs/COMMANDS.md](COMMANDS.md)。

### 方法 A：直接从 PyPI 构建

```bash
cd make_ansible_portable
./build.sh --source ansible-core==2.15.13 --clean-output
```

如果你要打的是 `2.10.x`，要注意官方包名是 `ansible-base`，例如：

```bash
./build.sh --source ansible-base==2.10.17 --clean-output
```

这会做几件事：

1. 下载官方 `ansible-core` 包
2. 用 `pip --target` 安装到便携目录
3. 写入便携入口 `__main__.py`
4. 生成 `ansible-playbook`、`ansible-galaxy` 等软链
5. 做一次 `localhost -m ping` 自测
6. 输出目录和 tar 包

默认 tar 包格式是 `tar.gz`。

默认还会把仓库自己的 `LICENSE`、`NOTICE`、`ACKNOWLEDGEMENTS.md` 和
`UPSTREAM-NOTICES.txt` 一起写进 bundle 根目录，避免你分发产物时把来源和
许可证说明丢掉。

### 方法 B：扔官方 wheel 进去构建

如果你已经有官方 wheel：

```bash
./build.sh --source /data/ansible_core-2.15.13-py3-none-any.whl --clean-output
```

### 方法 C：扔官方 sdist 进去构建

```bash
./build.sh --source /data/ansible-core-2.15.13.tar.gz --clean-output
```

## 4. 输出结果长什么样

默认输出到 `dist/`，例如：

```text
dist/
  portable-ansible-core-2.15.13/
    ansible/
    ansible-config -> ansible
    ansible-console -> ansible
    ansible-doc -> ansible
    ansible-galaxy -> ansible
    ansible-inventory -> ansible
    ansible-playbook -> ansible
    ansible-pull -> ansible
    ansible-vault -> ansible
    QUICKSTART.txt
    portable-manifest.json
  portable-ansible-core-2.15.13.tar.gz
```

## 4.1 如何切换压缩格式

默认使用 `gz`，因为构建和解压更快，兼容性也最好。

如果你想改成 `bz2`：

```bash
./build.sh --source ansible-core==2.15.13 --compression bz2 --clean-output
```

如果你想改成 `xz`：

```bash
./build.sh --source ansible-core==2.15.13 --compression xz --clean-output
```

支持的值：

- `gz`
- `bz2`
- `xz`

## 5. 如何运行便携包

进入解压目录后：

```bash
python3 ./ansible localhost -m ping
python3 ./ansible-playbook playbook.yml
python3 ./ansible-galaxy --version
```

如果只想快速验证本地可用：

```bash
python3 ./ansible localhost -m setup
```

## 6. 如何打入第三方 Python 包

这里的“第三方包”指 Python 依赖，例如：

- `PyMySQL`
- `boto3`
- `kubernetes`
- `requests`

工具把它们装进 `ansible/extras/`。便携入口会自动把 `extras/` 加入 `sys.path`。

### 方法 A：构建时直接打入

单个包：

```bash
./build.sh \
  --source ansible-core==2.15.13 \
  --extra-package PyMySQL \
  --extra-package requests
```

requirements 文件：

```bash
./build.sh \
  --source ansible-core==2.15.13 \
  --extra-requirements examples/extras-k8s.txt
```

### 方法 B：对已生成便携包追加安装

```bash
./install-extras.sh \
  --bundle dist/portable-ansible-core-2.15.13 \
  --extra-package boto3
```

或者：

```bash
./install-extras.sh \
  --bundle dist/portable-ansible-core-2.15.13 \
  --extra-requirements examples/extras-mysql.txt
```

安装完成后，信息会记录进 `portable-manifest.json`。

## 7. 常见 extras 示例

### MySQL

```bash
./build.sh \
  --source ansible-core==2.15.13 \
  --extra-requirements examples/extras-mysql.txt
```

### Kubernetes

```bash
./build.sh \
  --source ansible-core==2.15.13 \
  --extra-requirements examples/extras-k8s.txt
```

### AWS

```bash
./build.sh \
  --source ansible-core==2.15.13 \
  --extra-requirements examples/extras-aws.txt
```

## 8. 如何查看官方包自带依赖

这个命令会读取官方 wheel/sdist 的元数据：

```bash
./inspect-source.sh --source ansible-core==2.15.13
```

如果你想保存 JSON：

```bash
./inspect-source.sh --source ansible-core==2.15.13 --json > source-meta.json
```

这个功能适合你自己做“依赖锁定”或排错。

## 9. 如何批量测试末版并刷新 README

如果你想把 README 里的“已测试版本矩阵”自动刷新掉，不再手工改表，可以直接运行：

```bash
./refresh-tested-matrix.sh \
  --start-minor 2.10 \
  --python-candidate python3.9 \
  --python-candidate python3.10 \
  --python-candidate python3.11 \
  --python-candidate python3.12
```

这个命令会：

1. 查询 PyPI，从 `2.10` 开始找出每个 minor 的最后一个小版本
2. 读取每个官方包的 `Requires-Python`
3. 从你提供的 `--python-candidate` 里自动挑一个能跑这个 minor 的解释器
4. 对每个版本执行一次真实构建和 `localhost -m ping` 自测
5. 重写 `README.md` 里的矩阵，并把明细写入 `dist-tests/tested-matrix.json`

如果解释器不在 `PATH`，就直接给绝对路径：

```bash
./refresh-tested-matrix.sh \
  --start-minor 2.10 \
  --python-candidate /opt/python/3.9/bin/python3 \
  --python-candidate /opt/python/3.10/bin/python3 \
  --python-candidate /opt/python/3.11/bin/python3 \
  --python-candidate /opt/python/3.12/bin/python3
```

如果你想把某个 minor 强制绑到指定解释器：

```bash
./refresh-tested-matrix.sh \
  --start-minor 2.10 \
  --python-candidate python3.9 \
  --python-candidate python3.10 \
  --python-candidate python3.11 \
  --python-candidate python3.12 \
  --python-override 2.18=/opt/python/3.11/bin/python3
```

如果你只想生成 JSON，不改 README：

```bash
./refresh-tested-matrix.sh \
  --start-minor 2.10 \
  --python-candidate python3.9 \
  --python-candidate python3.10 \
  --python-candidate python3.11 \
  --python-candidate python3.12 \
  --skip-readme-update
```

## 10. 离线或半离线构建

### 先准备 wheelhouse

在线机器执行：

```bash
mkdir -p /tmp/wheelhouse
python3 -m pip download -d /tmp/wheelhouse ansible-core==2.15.13
python3 -m pip download -d /tmp/wheelhouse -r examples/extras-k8s.txt
```

然后把 `/tmp/wheelhouse` 拷到离线机器。

### 离线构建

```bash
./build.sh \
  --source /wheelhouse/ansible_core-2.15.13-py3-none-any.whl \
  --wheelhouse /wheelhouse \
  --offline \
  --clean-output
```

离线追加 extras：

```bash
./install-extras.sh \
  --bundle dist/portable-ansible-core-2.15.13 \
  --wheelhouse /wheelhouse \
  --offline \
  --extra-requirements examples/extras-k8s.txt
```

## 11. 常用参数

### build.sh

- `--source`: 必填。官方包 spec、wheel 路径或 sdist 路径
- `--bundle-name`: 自定义输出目录名
- `--output-dir`: 输出目录，默认 `dist`
- `--compression`: `gz`、`bz2`、`xz`，默认 `gz`
- `--clean-output`: 覆盖已有产物
- `--skip-archive`: 只生成目录，不打 tar 包
- `--skip-self-test`: 跳过 localhost 自测
- `--strip-metadata`: 删除 `*.dist-info` / `*.egg-info`，减小体积，但也可能删掉上游许可证元数据。公开分发产物前要谨慎使用
- `--wheelhouse`: 本地 wheel 目录
- `--offline`: 禁止访问 PyPI
- `--extra-package`: 额外 Python 包，可重复
- `--extra-requirements`: requirements 文件，可重复
- `--constraint`: extras 安装约束文件

### install-extras.sh

- `--bundle`: 已解压便携包目录
- `--extra-package`: 单个包
- `--extra-requirements`: requirements 文件
- `--constraint`: 约束文件
- `--wheelhouse`: 本地 wheel 目录
- `--offline`: 离线安装
- `--self-test`: 装完后跑一次 localhost 测试

### refresh-tested-matrix.sh

- `--start-minor`: 起始 minor，默认 `2.10`
- `--end-minor`: 可选结束 minor，不写时自动测到 PyPI 当前最新稳定 minor
- `--readme`: 要被重写矩阵的 README，默认 `README.md`
- `--output-dir`: 批量测试输出目录，默认 `dist-tests`
- `--results-json`: JSON 结果输出路径，默认 `dist-tests/tested-matrix.json`
- `--python-candidate`: 候选 Python，可重复
- `--python-override`: 为某个 minor 强制指定解释器，可重复，格式 `2.18=/path/to/python`
- `--skip-readme-update`: 只写 JSON，不改 README
- `--wheelhouse`: 本地 wheel 目录
- `--offline`: 构建时不访问 PyPI 包下载

## 12. 版本选择建议

这个工具不内置 Python，所以目标机器 Python 版本决定你能打哪一代 `ansible-core`。

实操建议：

- 如果目标机器普遍还是 Python 3.9，优先选 `ansible-core 2.15.x`
- 如果你能统一到更高 Python，再考虑更高版本的 `ansible-core`

最稳的做法是：

1. 先在目标环境确认 `python3 --version`
2. 再选择相应 `ansible-core` 版本
3. 最后用 `./build.sh --source ...` 真实打一次并跑通 `localhost -m ping`

## 13. 排错

### 错误：`No matching distribution found`

原因通常有三个：

- 目标 Python 版本太低
- 网络访问 PyPI 失败
- 你在离线模式下没有准备齐 wheelhouse

### 错误：某个第三方库 import 失败

一般是 extras 没打进去，或者打包后你运行的不是便携目录里的命令。

确认方式：

```bash
ls dist/portable-ansible-core-2.15.13/ansible/extras
```

### 错误：只想要目录，不想打 tar 包

加：

```bash
--skip-archive
```

### 错误：已有产物挡住了

加：

```bash
--clean-output
```

它的实际作用是：删除当前同名 bundle 目录，以及同名的旧 `tar.gz`、`tar.bz2`、`tar.xz` 包，然后重新构建。

## 14. 推荐工作流

推荐你按这个顺序用：

1. `./inspect-source.sh --source ansible-core==目标版本`
2. `./build.sh --source ansible-core==目标版本 --clean-output`
3. `python3 dist/<bundle>/ansible localhost -m ping`
4. `./install-extras.sh --bundle dist/<bundle> --extra-requirements 某个requirements.txt`
5. 再跑一次自测

这套流程适合自己维护“官方 core -> 便携包”的长期升级工作。
