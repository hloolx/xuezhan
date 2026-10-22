using UnrealBuildTool;
using System.Collections.Generic;

public class CivWarEditorTarget : TargetRules
{
	public CivWarEditorTarget(TargetInfo Target) : base(Target)
	{
		Type = TargetType.Editor;
		DefaultBuildSettings = BuildSettingsVersion.Latest;
		IncludeOrderVersion = EngineIncludeOrderVersion.Latest;
		ExtraModuleNames.Add("CivWar");
	}
}
