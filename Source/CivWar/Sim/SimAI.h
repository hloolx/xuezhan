// 血战文明 - 规则核心：单人模式 AI 对手
// AI 只能通过 Simulation::Apply 下达与玩家完全相同的指令，遵守相同的资源、训练和升级规则。
#pragma once

#include "Simulation.h"

namespace cw
{
	enum class AiDifficulty : uint8_t
	{
		Easy = 0,
		Normal,
		Hard,
	};

	struct AiConfig
	{
		AiDifficulty Difficulty = AiDifficulty::Normal;
		uint32_t Seed = 12345;
	};

	// 供调试/界面显示的 AI 意图
	enum class AiIntent : uint8_t
	{
		Idle = 0,
		Build,     // 正常出兵
		Defend,    // 前线压力大：防守
		SaveForAge,// 攒钱升级
		Push,      // 优势推进
	};

	class AiPlayer
	{
	public:
		AiPlayer(int32_t InTeam, const AiConfig& InConfig);

		void Tick(Simulation& Sim, float Dt);
		AiIntent Intent() const { return CurrentIntent; }
		int32_t TeamIndex() const { return Team; }

	private:
		struct Assessment
		{
			float MyArmyValue = 0.f;
			float EnemyArmyValue = 0.f;
			int32_t MyRoleCount[3] = { 0, 0, 0 };
			int32_t EnemyRoleCount[3] = { 0, 0, 0 };
			int32_t EnemyHeavyArmor = 0;
			int32_t EnemyLightArmor = 0;
			float EnemyFrontDistToMyBase = 1.0e9f; // 敌方最前单位到我方城门的距离
			float MyFrontDistToEnemyBase = 1.0e9f;
			bool bMyFrontIsMelee = false;
			float Pressure = 0.f; // 0~1+，越大越危险
		};

		// 攒钱目标：AI 先确定要攒钱做什么，再用剩余金币出兵，避免“有钱就花”导致永远建不起炮塔/升不了时代
		enum class SaveGoal : uint8_t
		{
			None = 0,
			Age,
			Turret,
			TurretSlot,
			Economy,
		};

		void Think(Simulation& Sim);
		Assessment Assess(const Simulation& Sim) const;
		bool TryCastSkill(Simulation& Sim, const Assessment& A);
		SaveGoal ChooseGoal(const Simulation& Sim, const Assessment& A, int32_t& OutCost) const;
		bool TryUpgradeAge(Simulation& Sim, const Assessment& A);
		bool TryBuildTurret(Simulation& Sim, const Assessment& A, SaveGoal Goal, int32_t GoalCost);
		int32_t DesiredEconomyLevel(const Simulation& Sim) const;
		void UpdateStance(Simulation& Sim, const Assessment& A, SaveGoal Goal);
		bool TryImproveTurrets(Simulation& Sim, const Assessment& A, int32_t Reserve);
		void TryChooseDoctrine(Simulation& Sim);
		void ControlChampion(Simulation& Sim, const Assessment& A);
		void TryLastStand(Simulation& Sim, const Assessment& A);
		bool TryTrain(Simulation& Sim, const Assessment& A, int32_t Reserve);
		int32_t ChooseUnitSlot(const Simulation& Sim, const Assessment& A);
		int32_t ChooseTurretDef(const Simulation& Sim, const Assessment& A) const;
		int32_t DesiredTurrets(const Simulation& Sim, const Assessment& A) const;
		int32_t BuiltTurrets(const Simulation& Sim) const;
		float Random01();
		bool Issue(Simulation& Sim, const Command& Cmd);

		int32_t Team = 1;
		AiConfig Config;
		float ThinkTimer = 0.f;
		float ThinkInterval = 0.5f;
		float ReactionNoise = 0.f; // 低难度下随机做出次优选择的概率
		uint32_t RngState = 1;
		AiIntent CurrentIntent = AiIntent::Idle;
		float LastStanceChange = -100.f;
		bool bChampionRetreating = false; // 统帅残血回城休整中
	};
}
