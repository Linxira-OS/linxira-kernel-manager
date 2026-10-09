# linxira-kernel-manager · Agent 开发规范

> **档位**:A · 系统源仓
> **本仓职责**:只读的内核与引导状态报告,并对固定操作生成计划(plan);PySide6 界面 + CLI。
> 通用约束见工作区总纲 `f:\Linxira-OS\AGENTS.md` 与发布规范 `linxira-os/docs/RELEASE_STANDARD.md`;
> 本文只写本仓特有内容。

## 职责与边界

- 支持矩阵**故意收窄**为 `linux` / `linux-lts` / `linux-headers` / `linux-lts-headers` 四者。
- 采集只读固定位置:`/usr/lib/modules`、`/boot`、`/proc` 以及固定的 GRUB 位置。
- 子进程为**固定 argv**:`/usr/bin/uname -r`、固定的 `pacman -Q` 查询、`dkms status`、
  `/usr/bin/grub-editenv list`;每次调用 `shell=False` 且带超时。
- GRUB 报告仅保留引导这两个受支持内核镜像的条目;任何 CLI 选项**都不接受**包名/内核名/模块名/命令/路径。
- 计划(plan)只含展示用的预期命令与效果;**apply 永远返回 `backend-not-ready`**。
- 计划带来源状态与 plan SHA-256 摘要,原子写入并以私有权限保存在
  `$XDG_STATE_HOME/linxira/kernel-manager/plans`。
- 应用**从不**调用提权工具、软件包变更、服务写入、initramfs 生成或引导加载器写入。
- 无参数启动 PySide6 界面(Overview / Kernels / Boot / Activity 视图);保存需复核确认,Apply 处于禁用状态。

## 目录布局

- `src/linxira_kernel_manager/`:`__init__.py`、`__main__.py`、`app.py`、`collector.py`、
  `policy.py`、`reporting.py`、`ui.py`、`about.py`
- `tests/`:`test_collector.py`、`test_plans.py`、`test_grub.py`、`test_cli_ui_metadata.py`、
  `test_about_metadata.py`、`helpers.py`
- `data/`:`org.linxira.KernelManager.desktop`、`org.linxira.KernelManager.metainfo.xml`

## 本地校验

CI(分支不限,python 3.11,需 `libegl1`)执行:

```sh
python -m pip install .
QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v
python -m compileall -q src tests
python -m pip wheel --no-deps --wheel-dir dist .
```

CLI 自检:

```sh
linxira-kernel-manager --report-json
linxira-kernel-manager --plan org.linxira.kernel.ensure-standard.v1
linxira-kernel-manager --plan org.linxira.kernel.boot-lts-once.v1
linxira-kernel-manager --plan org.linxira.kernel.regenerate-initramfs.v1
linxira-kernel-manager --plan org.linxira.bootloader.refresh-grub.v1
```

## 版本与发布

- 版本唯一来源是本仓根 `VERSION`(当前 `0.1.0`);`pyproject.toml` 的 `version` 必须同步。
- 改 `VERSION` 触发 `.github/workflows/release.yml`(分支 `main`)自动建 Release,进入 `[linxira]` 全自动链。**禁止手工 bump**。

## 禁区

- 保持"只读 + 计划展示"边界:不得让任何选项接受任意包名/内核名/模块名/命令/路径,不得接入提权、包变更、服务写入、initramfs 或引导加载器写入,`apply` 不得改为真实执行。
- 不引入 `cachyos` / `aur` / `seafoam`;不直接 `sudo`/`su`/`doas`/`run0`。
- 新增子进程必须沿用固定 argv + `shell=False` + 超时范式。
- 不 `git add -A`(勿带入 `dist/`、`build/`、`.pytest_cache/` 等产物)。