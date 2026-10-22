// 独立测试程序的数据加载：读取 Content/Data/*.json，与游戏内 DataTable 使用同一份数据
#pragma once

#include "Sim/SimTypes.h"

#include <string>

namespace harness
{
	bool LoadGameData(const std::string& DataDir, cw::GameData& Out, std::string& Error);
}
