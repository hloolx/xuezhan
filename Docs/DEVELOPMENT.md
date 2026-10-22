# 构建、验证与贡献

本仓库面向 Windows / Unreal Engine 5.8。安装方式和首次启动见 [README](../README.md)。

## 规则测试

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File Tools\civwar.ps1 simtest -Matches 20
```

该命令先检查八张规则数据表与 C++ 行结构是否一致，再通过 CMake / Visual Studio 2022 构建 `Tests/SimHarness` 并运行规则断言与 AI 对局。单独检查数据：`python Tools/check_data_schema.py`。

## Unreal 构建

`Tools/civwar.ps1` 支持 `build`、`content`、`setup`、`editor`、`run`、`host`、`join`、`nettest`、`package`。找不到引擎时设置 `UE_ROOT` 或传入 `-EngineRoot`。建议纯英文路径，避免特定 Windows 代码页与 MSVC 响应文件的兼容问题。`.uproject` 使用通用的 `5.8` 关联；若使用源码编译引擎，可自行重新关联。

公开版已带地图、基础材质、音效、音乐与字体；`setup` 会编译并运行内容准备脚本，已有资源默认保留。重新生成基础音效：

```powershell
python Tools/gen_sfx.py
powershell -NoProfile -ExecutionPolicy Bypass -File Tools\civwar.ps1 content
```

脚本生成的原始 WAV 在 `RawAssets/Audio/`，该目录默认忽略；UE 导入资源位于 `Content/Audio/`。

## 验证边界

- 公开版本的规则测试由 GitHub Actions 持续运行。
- `Tests/Art/`、部分 `Source/CivWar/Tests/` 和美术审查脚本针对作者的完整资源库，依赖未公开的模型、生产清单、截图或采样；不能把它们当作克隆即通过的公共测试集。
- 本次公开版本的实际检查结果记录在 [PUBLIC_RELEASE.md](PUBLIC_RELEASE.md)，区分规则测试、编译和运行。
- 联机代码已实现；局域网、公网、长时间性能、完整打包和真人试听需要独立验证，不能由规则测试结果推断。
- `Tools/` 中保留了美术与部署准备代码；部分脚本有原开发机路径默认值，使用前需配置自己的路径。常规 `simtest/setup/run` 不依赖私有美术工具。

## 贡献

规则变化先更新 `Content/Data/` 或 `Source/CivWar/Sim/`，并在适当情况下补充有实际行为意义的测试。提交前运行规则测试；修改 UE 层时另外验证编辑器目标。

项目自有代码按 [MIT](../LICENSE) 提交。新素材必须有来源与许可，保留原作者署名。作者私有模型与贴图、受限音效、生成服务账号、运行日志和带签名下载链接不属于公开仓库的提交范围。`.gitignore` 已排除常见私有路径，提交前仍应检查 `git diff --cached`。
