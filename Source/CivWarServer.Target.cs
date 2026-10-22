using UnrealBuildTool;
using System.Collections.Generic;

// 独立服务器目标：预留给后续的专用服务器部署。
// 注意：Epic Games Launcher 安装的二进制引擎不支持构建 Server 目标，需要源码版引擎；
// 第一轮使用监听服务器（Listen Server），不依赖此目标。
public class CivWarServerTarget : TargetRules
{
	public CivWarServerTarget(TargetInfo Target) : base(Target)
	{
		Type = TargetType.Server;
		DefaultBuildSettings = BuildSettingsVersion.Latest;
		IncludeOrderVersion = EngineIncludeOrderVersion.Latest;
		ExtraModuleNames.Add("CivWar");
	}
}
