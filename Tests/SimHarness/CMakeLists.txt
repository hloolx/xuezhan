cmake_minimum_required(VERSION 3.20)
project(CivWarSimHarness CXX)

# 规则核心（与游戏模块共用同一份源码）
set(SIM_DIR ${CMAKE_CURRENT_SOURCE_DIR}/../../Source/CivWar)

add_executable(SimHarness
	main.cpp
	JsonDataLoader.cpp
	${SIM_DIR}/Sim/SimTypes.cpp
	${SIM_DIR}/Sim/Simulation.cpp
	${SIM_DIR}/Sim/SimulationCommands.cpp
	${SIM_DIR}/Sim/SimChampion.cpp
	${SIM_DIR}/Sim/SimAI.cpp
)

target_include_directories(SimHarness PRIVATE ${SIM_DIR} ${CMAKE_CURRENT_SOURCE_DIR})
target_compile_features(SimHarness PRIVATE cxx_std_20)

if (MSVC)
	string(REPLACE "/EHsc" "" CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS}")
	# 尽量贴近 UE 的编译约束：高警告级别并视为错误（含变量遮蔽 C4456~C4459）、关闭异常与 RTTI、UTF-8 源码
	target_compile_options(SimHarness PRIVATE /W4 /WX /permissive- /utf-8 /GR- /EHs-c- /Zc:__cplusplus)
	target_compile_definitions(SimHarness PRIVATE _HAS_EXCEPTIONS=0 _CRT_SECURE_NO_WARNINGS)
else()
	target_compile_options(SimHarness PRIVATE -Wall -Wextra -Wshadow -Werror -fno-exceptions -fno-rtti)
endif()
