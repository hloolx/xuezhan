// 血战文明 - 规则核心：对局模拟（仅在服务器上运行，是唯一的权威状态）
#pragma once

#include "SimState.h"

#include <unordered_map>

namespace cw
{
	enum class EndReason : uint8_t
	{
		None = 0,
		BaseDestroyed,
		Forfeit,   // 对手离开/断线
		TimeLimit, // 到达时间上限（Winner 可能为 -1 表示平局）
	};

	class Simulation
	{
	public:
		explicit Simulation(const GameData& InData, uint32_t InSeed = 1u);

		// 重置为开局状态（阶段 NotStarted）；国策选项等随机内容由种子决定（服务器每局随机，测试固定）
		void Reset();
		void SetSeed(uint32_t InSeed) { Seed = InSeed != 0 ? InSeed : 1u; }
		void Start();
		// 以固定步长推进；调用方负责累积真实时间
		void Step(float Dt);
		// 发起方阵营由调用方（服务器）根据连接身份确定
		CommandResult Apply(int32_t InTeam, const Command& Cmd);
		// 只做校验、不修改状态：供界面提示和 AI 使用
		CommandResult Check(int32_t InTeam, const Command& Cmd) const;
		void Forfeit(int32_t LoserTeam);
		// 仅供服务器端压力测试使用（-cwstress），客户端没有任何途径调用
		void DebugGrantGold(int32_t InTeam, double Amount);
		// 仅供服务器端展示/截图测试使用（-cwshowcase）
		void DebugGrantXp(int32_t InTeam, double Amount);

		const GameData& Data() const { return GameDataRef; }
		MatchPhase Phase() const { return CurrentPhase; }
		int32_t Winner() const { return WinnerTeam; }
		EndReason GetEndReason() const { return Reason; }
		float Time() const { return SimTime; }
		const std::vector<Unit>& Units() const { return UnitList; }
		const std::vector<Projectile>& Projectiles() const { return ProjectileList; }
		const std::vector<SkillCast>& SkillCasts() const { return CastList; }
		const TeamState& Team(int32_t InTeam) const { return Teams[InTeam]; }
		const Unit* FindUnit(int32_t Id) const;

		// 事件在 Step/Apply 中累积，由调用方读取后清空
		const std::vector<SimEvent>& Events() const { return EventList; }
		void ClearEvents() { EventList.clear(); }

		// 战场几何（服务器坐标，阵营 0 在左、阵营 1 在右）
		float BaseX(int32_t InTeam) const;
		float BaseFrontX(int32_t InTeam) const;
		float TurretX(int32_t InTeam) const;
		static int32_t Dir(int32_t InTeam) { return InTeam == 0 ? 1 : -1; }
		static int32_t Enemy(int32_t InTeam) { return 1 - InTeam; }

		// 查询（界面/AI）
		std::vector<int32_t> TrainableUnits(int32_t InTeam) const;
		int32_t NextTurretSlotCost(int32_t InTeam) const; // 没有可购买槽位时返回 -1
		int32_t TurretUpgradeCost(int32_t InTeam, int32_t Slot) const; // 不可升级时返回 -1
		int32_t TurretSellValue(int32_t InTeam, int32_t Slot) const;
		float TurretDamage(int32_t TurretDef, int32_t Level) const;
		float TurretRange(int32_t TurretDef, int32_t Level) const;
		int32_t UnlockedTurretSlots(int32_t InTeam) const;
		int32_t EconomyUpgradeCost(int32_t InTeam) const; // 已满级返回 -1
		float IncomePerSecond(int32_t InTeam) const;     // 当前实际收入（含金矿与决战倍率）
		float HoldLineX(int32_t InTeam) const;           // 驻守线的世界 X 坐标
		int32_t UnitCost(int32_t InTeam, int32_t InDef) const;   // 含国策的实际造价
		float UnitTrainTime(int32_t InTeam, int32_t InDef) const;
		float TurretDamageFor(int32_t InTeam, int32_t TurretDef, int32_t Level) const; // 含国策
		float TurretRangeFor(int32_t InTeam, int32_t TurretDef, int32_t Level) const;
		float UnitRange(const Unit& U) const;
		const Unit* ChampionUnit(int32_t InTeam) const;  // 阵亡或未启用时为 nullptr
		const ChampionDef* CurrentChampion(int32_t InTeam) const;
		float ChampionAbilityCooldown(int32_t InTeam) const; // 含国策的冷却时长
		float ChampionRespawnTime(int32_t InTeam) const;
		int32_t VeteranRankFor(const Unit& U, float Value) const;
		bool IsSuddenDeath() const;
		float BaseDamageMultiplier() const;
		float IncomeMultiplier() const;
		float TurretDamageMultiplier() const;
		// 返回 [Min, Max] 合法技能落点
		void SkillTargetRange(int32_t InTeam, float& OutMin, float& OutMax) const;

	private:
		// 近战命中先登记、在所有单位行动后统一结算：同一步内互相砍杀的双方都能出手，消除阵营处理顺序带来的先手优势
		struct PendingHit
		{
			int32_t AttackerTeam = 0;
			int32_t TargetId = TargetNone;
			float Damage = 0.f;
			DamageType Type = DamageType::Normal;
			float StructureMult = 1.f;
			float SplashX = 0.f;
			float SplashRadius = 0.f;
			int32_t AttackerId = -1;
		};

		void RebuildIndex();
		void BuildOrders();
		Unit* FindUnitMutable(int32_t Id);
		bool IsAlive(const Unit& U) const { return U.State != UnitState::Dying; }
		float EdgeDistance(const Unit& A, const Unit& B) const;
		float EdgeDistanceToBase(const Unit& A, int32_t BaseTeam) const;
		bool IsTargetValid(const Unit& U, int32_t TargetId) const;
		int32_t SelectTarget(const Unit& U) const;

		void StepEconomy(float Dt);
		void StepTraining(float Dt);
		void StepAgeUpgrades(float Dt);
		void StepUnits(float Dt);
		void StepTeamUnits(int32_t InTeam, float Dt);
		void ApplyPendingHits();
		void StepProjectiles(float Dt);
		void StepTurrets(float Dt);
		void StepSkills(float Dt);
		void StepDeaths(float Dt);
		void StepChampions(float Dt);

		bool TrySpawn(int32_t InTeam, int32_t Def);
		Unit& AddUnit(int32_t InTeam, int32_t Def, float X, int32_t Row, bool bChampion);
		void SpawnChampion(int32_t InTeam);
		void EvolveChampion(int32_t InTeam);
		float ChampionTargetProgress(int32_t InTeam, const Unit& Champ) const;
		void StepChampionMovement(Unit& U, int32_t InTeam, float Dt);
		// 根据数据表、国策、老兵等级与统帅加成重新计算单位属性；生命按比例保持
		void RefreshUnitStats(Unit& U);
		void RefreshTeamUnits(int32_t InTeam);
		float UnitDamageMultiplier(const Unit& U) const; // 含光环与战吼
		float UnitAttackInterval(const Unit& U) const;
		void CreditKill(int32_t AttackerUnitId, float Value);
		void GrantDoctrinePick(int32_t InTeam);
		void GenerateOffer(int32_t InTeam);
		void ApplyDoctrineEffects(int32_t InTeam);
		uint32_t NextRandom();
		void ResolveUnitAttack(Unit& U);
		void LaunchProjectile(int32_t InTeam, int32_t SourceUnit, int32_t SourceSlot, int32_t TargetId,
			float FromX, float TargetX, float Speed, float Damage, float Splash, float StructureMult, DamageType Type);
		void DamageUnit(Unit& Target, float RawDamage, DamageType Type, int32_t AttackerTeam, bool bFromTurret = false, int32_t AttackerUnitId = -1);
		void DamageBase(int32_t BaseTeam, float RawDamage, DamageType Type, float StructureMult, int32_t AttackerTeam);
		void SplashDamage(int32_t AttackerTeam, float CenterX, float Radius, float RawDamage, DamageType Type, int32_t ExcludeId,
			bool bFromTurret = false, int32_t AttackerUnitId = -1);
		void KillUnit(Unit& U, int32_t KillerTeam, bool bByTurret, int32_t AttackerUnitId);
		void EndMatch(int32_t InWinner, EndReason InReason);
		void EndByTimeLimit();
		void Emit(EventType Type, int32_t InTeam, int32_t A = 0, int32_t B = 0, float X = 0.f, float Value = 0.f);
		void Pay(int32_t InTeam, int32_t Gold);

		GameData GameDataRef;
		uint32_t Seed = 1u;
		uint32_t RngState = 1u;
		float MaxUnitRadius = 0.f;
		MatchPhase CurrentPhase = MatchPhase::NotStarted;
		int32_t WinnerTeam = -1;
		EndReason Reason = EndReason::None;
		float SimTime = 0.f;
		uint32_t TickCount = 0;
		bool bSuddenDeathAnnounced = false;
		int32_t NextUnitId = 1;
		int32_t NextProjectileId = 1;
		int32_t NextCastId = 1;
		TeamState Teams[TeamCount];
		std::vector<Unit> UnitList;
		std::vector<Projectile> ProjectileList;
		std::vector<SkillCast> CastList;
		std::vector<SimEvent> EventList;
		std::vector<PendingHit> PendingHits;
		std::unordered_map<int32_t, int32_t> IdToIndex;
		// 每队按“前进方向”从前到后排列的存活单位下标
		std::vector<int32_t> Order[TeamCount];
		std::vector<int32_t> BehindScratch;
	};
}
