using UnrealBuildTool;
using System.Collections.Generic;

public class CivWarTarget : TargetRules
{
	public CivWarTarget(TargetInfo Target) : base(Target)
	{
		Type = TargetType.Game;
		DefaultBuildSettings = BuildSettingsVersion.Latest;
		IncludeOrderVersion = EngineIncludeOrderVersion.Latest;
		ExtraModuleNames.Add("CivWar");
	}
}
