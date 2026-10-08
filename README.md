# macso

用于在 GitHub Actions 提供的临时 macOS 15 环境中开发、编译和测试仓库项目。

## 网页远程桌面

需要可视化操作时，选择 Actions → **macOS Web Desktop** → **Run workflow**。批准该次临时设备后，打开运行摘要中的私人网页地址，用仓库 `MACOS_PASSWORD` 登录。已实测真实桌面、鼠标、快捷键和中文输入；详细步骤及结束方法见 [DESKTOP.md](DESKTOP.md)。

## 自动测试使用方式

1. 打开 [Actions](https://github.com/Verkuang/macso/actions)。
2. 选择 **macOS Project Tests**，点击 **Run workflow**。
3. 打开运行记录查看系统、Xcode、Swift 版本，以及测试步骤和结果。

提交代码到 main 或创建 Pull Request 也会自动运行。

## 当前验证范围

工作流确认 macOS 系统、Xcode/macOS SDK 和 Swift 工具链可用，并编译、执行一个 Swift 环境检查程序。

仓库尚未接入实际项目。缺少 `tests/macos.sh` 时，应用测试会明确标记为 **SKIPPED**，环境验证通过不代表应用测试通过。

## 接入实际项目

把项目代码添加到仓库，并创建 `tests/macos.sh`，在其中写入安装依赖及项目的真实测试命令。工作流会在 macOS 上执行：

```bash
bash -euo pipefail tests/macos.sh
```

例如 Swift Package 项目可以在该文件中写入 `swift test`。Xcode、Python、Node.js 项目应按实际项目配置安装依赖并运行测试。

## 环境说明

- 系统：`macos-15-intel`，具体版本和架构在每次运行日志及摘要中显示。
- 环境验证和项目测试共用一台机器，工作流最多 30 分钟；项目测试步骤最多 20 分钟。
- 每次运行使用临时机器，工作完成后释放，不保留为长期云电脑。
- 自动测试无需登录密码；网页桌面使用仓库 Secret `MACOS_PASSWORD`。
- 仓库目前为公开仓库，代码和运行日志公开；密钥应使用 GitHub Actions Secrets，不要提交到代码或打印到日志。
