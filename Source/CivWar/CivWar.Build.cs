using UnrealBuildTool;

public class CivWar : ModuleRules
{
	public CivWar(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

		// 允许以模块根目录为基准包含头文件，例如 #include "Sim/Simulation.h"
		PublicIncludePaths.Add(ModuleDirectory);

		PublicDependencyModuleNames.AddRange(new string[]
		{
			"Core",
			"CoreUObject",
			"Engine",
			"InputCore",
			"EnhancedInput",
			"NetCore",
			"Slate",
			"SlateCore",
			"UMG",
			"ProceduralMeshComponent",
			"Json",
			"JsonUtilities",
		});

		PrivateDependencyModuleNames.AddRange(new string[]
		{
			"ApplicationCore",
			"AudioMixer",
			"Sockets",
		});

		// 规则核心（Sim/）使用标准库且不依赖异常与 RTTI，与独立测试程序的编译约束一致
		bEnableExceptions = false;
		bUseRTTI = false;
	}
}
