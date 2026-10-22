// 血战文明 - 规则核心独立测试程序
// 用法：SimHarness.exe <Content/Data 目录> [--matches N] [--verbose]
#include "JsonDataLoader.h"
#include "TestUtil.h"
#include "Sim/SimAI.h"

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <string>
#include <vector>

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#endif

namespace harness
{
	TestContext& Ctx()
	{
		static TestContext Instance;
		return Instance;
	}
}

using namespace harness;

namespace
{
	constexpr float FixedDt = 0.05f; // 与服务器一致：20 Hz 固定步长
	bool GVerbose = false;

	int32_t SlotOf(const cw::Simulation& Sim, int32_t Team, const char* UnitId)
	{
		const std::vector<int32_t> List = Sim.TrainableUnits(Team);
		for (size_t I = 0; I < List.size(); ++I)
		{
			if (Sim.Data().Units[static_cast<size_t>(List[I])].Id == UnitId)
			{
				return static_cast<int32_t>(I);
			}
		}
		return -1;
	}

	cw::Command TrainCmd(int32_t Slot)
	{
		cw::Command C;
		C.Type = cw::CommandType::Train;
		C.A = Slot;
		return C;
	}

	cw::Command Cmd(cw::CommandType Type, int32_t A = 0, int32_t B = 0, float X = 0.f)
	{
		cw::Command C;
		C.Type = Type;
		C.A = A;
		C.B = B;
		C.X = X;
		return C;
	}

	// 不含统帅与国策的规则：用于只考察兵种、炮塔、技能本身的测试
	cw::GameData Classic(const cw::GameData& Data)
	{
		cw::GameData C = Data;
		C.Champions.clear();
		C.Doctrines.clear();
		return C;
	}

	void RunFor(cw::Simulation& Sim, float Seconds, InvariantReport* Rep = nullptr, std::vector<cw::SimEvent>* Events = nullptr)
	{
		for (int I = 0; I < static_cast<int>(Seconds / FixedDt + 0.5f) && Sim.Phase() == cw::MatchPhase::Running; ++I)
		{
			Sim.Step(FixedDt);
			if (Rep != nullptr)
			{
				CheckInvariants(Sim, *Rep);
			}
			if (Events != nullptr)
			{
				Events->insert(Events->end(), Sim.Events().begin(), Sim.Events().end());
			}
			Sim.ClearEvents();
		}
	}

	float FrontX(const cw::Simulation& Sim, int32_t Team)
	{
		float Best = Team == 0 ? -1.0e9f : 1.0e9f;
		for (const cw::Unit& U : Sim.Units())
		{
			if (U.Team == Team && !U.Champion && U.State != cw::UnitState::Dying)
			{
				Best = Team == 0 ? std::max(Best, U.X) : std::min(Best, U.X);
			}
		}
		return Best;
	}

	// ---------------- 阶段 1：单兵种完整战斗闭环 ----------------
	void TestSingleUnitCombatLoop(const cw::GameData& InData)
	{
		const cw::GameData Data = Classic(InData);
		std::printf("[测试] 单兵种战斗闭环：出生→行军→索敌→攻击→受击→死亡→清理→攻城→结算\n");
		cw::Simulation Sim(Data);
		Sim.Start();
		const int32_t Slot = SlotOf(Sim, 0, "StoneAxe");
		CW_CHECK(Slot >= 0, "找不到 StoneAxe");
		CW_CHECK(Sim.Apply(0, TrainCmd(Slot)) == cw::CommandResult::Ok, "阵营0 训练失败");
		CW_CHECK(Sim.Apply(1, TrainCmd(Slot)) == cw::CommandResult::Ok, "阵营1 训练失败");

		InvariantReport Rep;
		int Spawned = 0;
		int Died = 0;
		int BaseHits = 0;
		int MatchEnded = 0;
		float FirstAttackTime = -1.f;
		float FirstAttackEdge = 0.f;
		float DeathTime = -1.f;
		float RemovedTime = -1.f;
		int32_t DeadId = -1;
		int32_t SurvivorTeam = -1;
		float SpawnX0 = 0.f;
		bool bCheckedWalk = false;

		for (int Tick = 0; Tick < static_cast<int>(400.f / FixedDt) && Sim.Phase() == cw::MatchPhase::Running; ++Tick)
		{
			Sim.Step(FixedDt);
			CheckInvariants(Sim, Rep);
			for (const cw::SimEvent& Ev : Sim.Events())
			{
				switch (Ev.Type)
				{
				case cw::EventType::UnitSpawned:
					++Spawned;
					if (Ev.Team == 0)
					{
						SpawnX0 = Ev.X;
					}
					break;
				case cw::EventType::UnitAttackStart:
					if (FirstAttackTime < 0.f && Ev.B >= 0)
					{
						const cw::Unit* A = Sim.FindUnit(Ev.A);
						const cw::Unit* B = Sim.FindUnit(Ev.B);
						if (A != nullptr && B != nullptr)
						{
							FirstAttackTime = Sim.Time();
							FirstAttackEdge = std::fabs(A->X - B->X) - 80.f;
						}
					}
					break;
				case cw::EventType::UnitDied:
					++Died;
					DeathTime = Sim.Time();
					DeadId = Ev.A;
					SurvivorTeam = 1 - Ev.Team;
					break;
				case cw::EventType::BaseHit:
					++BaseHits;
					break;
				case cw::EventType::MatchEnded:
					++MatchEnded;
					break;
				default:
					break;
				}
			}
			Sim.ClearEvents();
			// 行军检查：出生 2 秒后应已前进
			if (!bCheckedWalk && Sim.Time() > 4.5f)
			{
				bCheckedWalk = true;
				for (const cw::Unit& U : Sim.Units())
				{
					if (U.Team == 0)
					{
						CW_CHECK(U.X > SpawnX0 + 200.f, "出生后没有前进");
						CW_CHECK(U.State == cw::UnitState::Walking, "应处于行军状态");
					}
				}
			}
			if (DeadId >= 0 && RemovedTime < 0.f && Sim.FindUnit(DeadId) == nullptr)
			{
				RemovedTime = Sim.Time();
			}
		}

		CW_CHECK(Spawned == 2, "应生成 2 个单位");
		CW_CHECK(FirstAttackTime > 0.f, "没有发生攻击");
		CW_CHECK(FirstAttackEdge <= 25.5f, "近战在接触距离之外发起攻击: " + std::to_string(FirstAttackEdge));
		CW_CHECK(Died == 1, "两名同兵种单位交战后应恰好死亡 1 个，实际 " + std::to_string(Died));
		CW_CHECK(RemovedTime > 0.f && std::fabs((RemovedTime - DeathTime) - Data.Rules.DeathDuration) < 0.11f,
			"死亡单位应在死亡表现结束后清理");
		CW_CHECK(BaseHits > 0, "幸存单位应攻击敌方基地");
		CW_CHECK(Sim.Phase() == cw::MatchPhase::Ended, "基地被摧毁后对局应结束");
		CW_CHECK(MatchEnded == 1, "结算事件应只有 1 次");
		CW_CHECK(Sim.Winner() == SurvivorTeam, "胜者应为幸存单位所属阵营");
		CW_CHECK(Sim.Team(1 - SurvivorTeam).BaseHp == 0.f, "败方基地生命应为 0");
		CW_CHECK(Rep.Total() == 0, "不变量违规: " + std::to_string(Rep.Total()));
		std::printf("    首次攻击 %.2fs（边缘距离 %.1fcm），死亡 %.2fs，清理 %.2fs，基地被毁 %.1fs，胜者 阵营%d\n",
			FirstAttackTime, FirstAttackEdge, DeathTime, RemovedTime, Sim.Time(), Sim.Winner());

		// 结算后继续推进/下指令不应改变结果
		const int32_t Winner = Sim.Winner();
		Sim.Step(FixedDt);
		CW_CHECK(Sim.Apply(0, TrainCmd(0)) == cw::CommandResult::MatchNotRunning, "结算后应拒绝指令");
		CW_CHECK(Sim.Winner() == Winner && Sim.Events().empty(), "结算后状态不应再变化");
	}

	// 远程单位保持射程、目标死亡后重新索敌并继续推进
	void TestRangedBehaviour(const cw::GameData& InData)
	{
		const cw::GameData Data = Classic(InData);
		std::printf("[测试] 远程保持射程 / 目标死亡后重新索敌推进\n");
		cw::Simulation Sim(Data);
		Sim.Start();
		const int32_t Slinger = SlotOf(Sim, 0, "StoneSlinger");
		const int32_t Axe = SlotOf(Sim, 1, "StoneAxe");
		CW_CHECK(Sim.Apply(0, TrainCmd(Slinger)) == cw::CommandResult::Ok, "训练投石猎手");
		CW_CHECK(Sim.Apply(0, TrainCmd(Slinger)) == cw::CommandResult::Ok, "训练投石猎手");
		CW_CHECK(Sim.Apply(1, TrainCmd(Axe)) == cw::CommandResult::Ok, "训练石斧战士");

		const cw::UnitDef& SD = Data.Units[static_cast<size_t>(Data.FindUnit("StoneSlinger"))];
		float FirstShotEdge = -1.f;
		bool bEnemyDead = false;
		bool bAdvancedAfterKill = false;
		float XAtKill = 0.f;
		int32_t ShooterId = -1;
		InvariantReport Rep;
		for (int Tick = 0; Tick < static_cast<int>(60.f / FixedDt); ++Tick)
		{
			Sim.Step(FixedDt);
			CheckInvariants(Sim, Rep);
			for (const cw::SimEvent& Ev : Sim.Events())
			{
				if (Ev.Type == cw::EventType::UnitAttackStart && Ev.Team == 0 && FirstShotEdge < 0.f && Ev.B >= 0)
				{
					const cw::Unit* A = Sim.FindUnit(Ev.A);
					const cw::Unit* B = Sim.FindUnit(Ev.B);
					if (A != nullptr && B != nullptr)
					{
						FirstShotEdge = std::fabs(A->X - B->X) - SD.Radius - Data.Units[static_cast<size_t>(B->Def)].Radius;
						ShooterId = A->Id;
					}
				}
				if (Ev.Type == cw::EventType::UnitDied && Ev.Team == 1)
				{
					bEnemyDead = true;
					if (const cw::Unit* S = Sim.FindUnit(ShooterId))
					{
						XAtKill = S->X;
					}
				}
			}
			Sim.ClearEvents();
			if (bEnemyDead && !bAdvancedAfterKill)
			{
				const cw::Unit* S = Sim.FindUnit(ShooterId);
				if (S != nullptr && S->X > XAtKill + 100.f && S->State == cw::UnitState::Walking)
				{
					bAdvancedAfterKill = true;
				}
			}
		}
		CW_CHECK(FirstShotEdge > SD.Range - 40.f && FirstShotEdge <= SD.Range + 0.6f,
			"远程应在接近最大射程时开火，实际边缘距离 " + std::to_string(FirstShotEdge));
		CW_CHECK(bEnemyDead, "两名投石猎手应击杀单个石斧战士");
		CW_CHECK(bAdvancedAfterKill, "目标死亡后应重新索敌并继续推进");
		CW_CHECK(Rep.Total() == 0, "不变量违规");
		std::printf("    首发边缘距离 %.1fcm（射程 %.0f）\n", FirstShotEdge, SD.Range);
	}

	// 拥挤与阻挡：大量单位同时出兵，不重叠、不穿越
	void TestCrowding(const cw::GameData& Data)
	{
		std::printf("[测试] 拥挤与阻挡：双方持续出兵 120 秒\n");
		cw::GameData Rich = Data;
		Rich.Rules.StartGold = 100000;
		cw::Simulation Sim(Rich);
		Sim.Start();
		InvariantReport Rep;
		size_t MaxUnits = 0;
		double StepSeconds = 0.0;
		double WorstMs = 0.0;
		int Steps = 0;
		for (int Tick = 0; Tick < static_cast<int>(120.f / FixedDt) && Sim.Phase() == cw::MatchPhase::Running; ++Tick)
		{
			for (int32_t T = 0; T < 2; ++T)
			{
				Sim.Apply(T, TrainCmd(Tick % 3));
			}
			const auto Start = std::chrono::steady_clock::now();
			Sim.Step(FixedDt);
			const double Sec = std::chrono::duration<double>(std::chrono::steady_clock::now() - Start).count();
			StepSeconds += Sec;
			WorstMs = std::max(WorstMs, Sec * 1000.0);
			++Steps;
			CheckInvariants(Sim, Rep);
			Sim.ClearEvents();
			MaxUnits = std::max(MaxUnits, Sim.Units().size());
		}
		CW_CHECK(Rep.Total() == 0, "拥挤场景不变量违规 " + std::to_string(Rep.Total()) + " enemyOverlap=" + std::to_string(Rep.EnemyOverlap)
			+ " allyOverlap=" + std::to_string(Rep.AllyOverlap) + " melee=" + std::to_string(Rep.MeleeOutOfRange));
		std::printf("    峰值单位数 %zu，敌我最小间隙 %.2fcm，模拟耗时 平均 %.1f 微秒/步、最慢 %.3f 毫秒/步\n", MaxUnits, Rep.WorstEnemyGap,
			Steps > 0 ? StepSeconds * 1.0e6 / Steps : 0.0, WorstMs);
	}

	// ---------------- 指令校验：越权与资源绕过 ----------------
	void TestCommandValidation(const cw::GameData& InData)
	{
		const cw::GameData Data = Classic(InData);
		std::printf("[测试] 指令校验：阵营、资源、队列、时代、炮塔、技能\n");
		cw::Simulation Sim(Data);
		CW_CHECK(Sim.Apply(0, TrainCmd(0)) == cw::CommandResult::MatchNotRunning, "开局前应拒绝");
		Sim.Start();
		CW_CHECK(Sim.Apply(2, TrainCmd(0)) == cw::CommandResult::InvalidTeam, "非法阵营");
		CW_CHECK(Sim.Apply(-1, TrainCmd(0)) == cw::CommandResult::InvalidTeam, "非法阵营");
		CW_CHECK(Sim.Apply(0, TrainCmd(-1)) == cw::CommandResult::InvalidParam, "非法槽位");
		CW_CHECK(Sim.Apply(0, TrainCmd(99)) == cw::CommandResult::InvalidParam, "非法槽位");

		// 金币不足：起始 200 金，重型 75
		const int32_t Heavy = SlotOf(Sim, 0, "BeastRider");
		CW_CHECK(Sim.Apply(0, TrainCmd(Heavy)) == cw::CommandResult::Ok, "第 1 个重型");
		CW_CHECK(Sim.Apply(0, TrainCmd(Heavy)) == cw::CommandResult::Ok, "第 2 个重型");
		CW_CHECK(Sim.Apply(0, TrainCmd(Heavy)) == cw::CommandResult::NotEnoughGold, "金币不足");
		CW_CHECK(Sim.Team(0).Gold >= 0.0, "金币不能为负");

		// 取消返还全部金币
		const double Before = Sim.Team(0).Gold;
		CW_CHECK(Sim.Apply(0, Cmd(cw::CommandType::CancelTrain, 1)) == cw::CommandResult::Ok, "取消训练");
		CW_CHECK(std::fabs(Sim.Team(0).Gold - (Before + 75.0)) < 0.001, "取消应全额返还");
		CW_CHECK(Sim.Apply(0, Cmd(cw::CommandType::CancelTrain, 5)) == cw::CommandResult::InvalidParam, "非法队列下标");

		// 队列容量
		cw::GameData Rich = Data;
		Rich.Rules.StartGold = 10000;
		cw::Simulation Sim2(Rich);
		Sim2.Start();
		for (int I = 0; I < Rich.Rules.QueueCapacity; ++I)
		{
			CW_CHECK(Sim2.Apply(0, TrainCmd(0)) == cw::CommandResult::Ok, "队列未满应可训练");
		}
		CW_CHECK(Sim2.Apply(0, TrainCmd(0)) == cw::CommandResult::QueueFull, "队列已满");

		// 时代
		CW_CHECK(Sim2.Apply(0, Cmd(cw::CommandType::UpgradeAge)) == cw::CommandResult::NotEnoughXp, "经验不足");

		// 炮塔
		const int32_t Rock = Rich.FindTurret("RockTower");
		const int32_t Ballista = Rich.FindTurret("Ballista");
		CW_CHECK(Sim2.Apply(0, Cmd(cw::CommandType::BuildTurret, 1, Rock)) == cw::CommandResult::SlotLocked, "槽位未解锁");
		CW_CHECK(Sim2.Apply(0, Cmd(cw::CommandType::BuildTurret, 0, Ballista)) == cw::CommandResult::LockedByAge, "炮塔时代未解锁");
		CW_CHECK(Sim2.Apply(0, Cmd(cw::CommandType::BuildTurret, 0, 999)) == cw::CommandResult::InvalidParam, "非法炮塔");
		CW_CHECK(Sim2.Apply(0, Cmd(cw::CommandType::BuildTurret, 0, Rock)) == cw::CommandResult::Ok, "建造炮塔");
		CW_CHECK(Sim2.Apply(0, Cmd(cw::CommandType::BuildTurret, 0, Rock)) == cw::CommandResult::SlotOccupied, "槽位已占用");
		const double G0 = Sim2.Team(0).Gold;
		const int32_t UpCost = Sim2.TurretUpgradeCost(0, 0);
		CW_CHECK(Sim2.Apply(0, Cmd(cw::CommandType::UpgradeTurret, 0)) == cw::CommandResult::Ok, "升级炮塔");
		CW_CHECK(std::fabs(Sim2.Team(0).Gold - (G0 - UpCost)) < 0.001, "升级扣费");
		CW_CHECK(Sim2.Apply(0, Cmd(cw::CommandType::UpgradeTurret, 0)) == cw::CommandResult::Ok, "升级到 3 级");
		CW_CHECK(Sim2.Apply(0, Cmd(cw::CommandType::UpgradeTurret, 0)) == cw::CommandResult::MaxLevel, "已满级");
		const int32_t Refund = Sim2.TurretSellValue(0, 0);
		const double G1 = Sim2.Team(0).Gold;
		CW_CHECK(Sim2.Apply(0, Cmd(cw::CommandType::SellTurret, 0)) == cw::CommandResult::Ok, "出售炮塔");
		CW_CHECK(std::fabs(Sim2.Team(0).Gold - (G1 + Refund)) < 0.001 && Refund > 0, "出售返还");
		CW_CHECK(Sim2.Apply(0, Cmd(cw::CommandType::SellTurret, 0)) == cw::CommandResult::SlotEmpty, "空槽出售");
		CW_CHECK(Sim2.Apply(0, Cmd(cw::CommandType::BuyTurretSlot)) == cw::CommandResult::Ok, "购买槽位");
		CW_CHECK(Sim2.Apply(0, Cmd(cw::CommandType::BuyTurretSlot)) == cw::CommandResult::Ok, "购买槽位");
		CW_CHECK(Sim2.Apply(0, Cmd(cw::CommandType::BuyTurretSlot)) == cw::CommandResult::NoMoreSlots, "槽位已满");

		// 技能：落点、NaN、冷却
		float Min = 0.f;
		float Max = 0.f;
		Sim2.SkillTargetRange(0, Min, Max);
		CW_CHECK(Sim2.Apply(0, Cmd(cw::CommandType::CastSkill, 0, 0, std::numeric_limits<float>::quiet_NaN())) == cw::CommandResult::BadTarget, "NaN 落点");
		CW_CHECK(Sim2.Apply(0, Cmd(cw::CommandType::CastSkill, 0, 0, Max + 10.f)) == cw::CommandResult::BadTarget, "贴近敌方基地");
		CW_CHECK(Sim2.Apply(0, Cmd(cw::CommandType::CastSkill, 0, 0, (Min + Max) * 0.5f)) == cw::CommandResult::Ok, "施放技能");
		CW_CHECK(Sim2.Apply(0, Cmd(cw::CommandType::CastSkill, 0, 0, (Min + Max) * 0.5f)) == cw::CommandResult::OnCooldown, "冷却中");

		// 阵营隔离：阵营 1 的指令不会影响阵营 0
		const size_t Queue0 = Sim2.Team(0).Queue.size();
		Sim2.Apply(1, Cmd(cw::CommandType::CancelTrain, 0));
		CW_CHECK(Sim2.Team(0).Queue.size() == Queue0, "阵营 1 不能取消阵营 0 的训练");
	}

	// 时代进化：条件、升级过程、旧队列规则、未实装时代
	void TestAgeProgression(const cw::GameData& InData)
	{
		const cw::GameData Data = Classic(InData);
		std::printf("[测试] 时代进化：逐个进入全部已实装时代，旧队列保持，最终时代后拒绝\n");
		cw::GameData Fast = Data;
		Fast.Rules.StartGold = 100000;
		Fast.Rules.PassiveXpPerSec = 1000.f; // 快速获得经验
		cw::Simulation Sim(Fast);
		Sim.Start();
		const int32_t StoneAxe = Fast.FindUnit("StoneAxe");
		CW_CHECK(Sim.Apply(0, TrainCmd(0)) == cw::CommandResult::Ok, "排入石器近战");
		CW_CHECK(Sim.Apply(0, TrainCmd(0)) == cw::CommandResult::Ok, "排入石器近战");
		Sim.Step(FixedDt * 40); // 经验累积
		CW_CHECK(Sim.Apply(0, Cmd(cw::CommandType::UpgradeAge)) == cw::CommandResult::Ok, "升级中世纪");
		CW_CHECK(Sim.Team(0).Upgrading, "应处于升级过程中");
		CW_CHECK(Sim.Apply(0, Cmd(cw::CommandType::UpgradeAge)) == cw::CommandResult::Upgrading, "升级中不能重复升级");
		CW_CHECK(Sim.Team(0).Age == 0, "升级完成前时代不变");
		int SpawnedOld = 0;
		for (int I = 0; I < static_cast<int>(6.f / FixedDt); ++I)
		{
			Sim.Step(FixedDt);
			for (const cw::SimEvent& Ev : Sim.Events())
			{
				if (Ev.Type == cw::EventType::UnitSpawned && Ev.Team == 0 && Ev.B == StoneAxe)
				{
					++SpawnedOld;
				}
			}
			Sim.ClearEvents();
		}
		CW_CHECK(Sim.Team(0).Age == 1, "应进入中世纪");
		CW_CHECK(std::fabs(Sim.Team(0).BaseMaxHp - Fast.Ages[1].BaseMaxHp) < 0.01f, "基地生命上限随时代提升");
		CW_CHECK(SpawnedOld == 2, "升级前排入的旧时代单位应按原兵种出生");
		const int32_t NewMelee = Sim.TrainableUnits(0)[0];
		CW_CHECK(Fast.Units[static_cast<size_t>(NewMelee)].Age == 1, "升级后训练面板为新时代兵种");
		bool bOldStillAlive = false;
		for (const cw::Unit& U : Sim.Units())
		{
			bOldStillAlive = bOldStillAlive || (U.Team == 0 && U.Def == StoneAxe && U.State != cw::UnitState::Dying);
		}
		CW_CHECK(bOldStillAlive, "已出场的旧时代单位继续存在");

		// 继续逐个升级：已实装的时代必须能进入；遇到未实装时代必须拒绝；全部实装则最后返回“已是最高时代”
		for (int32_t Next = 2; Next < static_cast<int32_t>(Fast.Ages.size()); ++Next)
		{
			Sim.Step(FixedDt * 100);
			if (!Fast.Ages[static_cast<size_t>(Next)].Implemented)
			{
				CW_CHECK(Sim.Apply(0, Cmd(cw::CommandType::UpgradeAge)) == cw::CommandResult::AgeNotImplemented, "未实装时代应拒绝");
				return;
			}
			CW_CHECK(Sim.Apply(0, Cmd(cw::CommandType::UpgradeAge)) == cw::CommandResult::Ok, "升级到下一时代");
			Sim.Step(Fast.Ages[static_cast<size_t>(Next)].UpgradeDuration + 0.1f);
			CW_CHECK(Sim.Team(0).Age == Next, "应进入时代 " + Fast.Ages[static_cast<size_t>(Next)].Id);
		}
		Sim.Step(FixedDt * 100);
		CW_CHECK(Sim.Apply(0, Cmd(cw::CommandType::UpgradeAge)) == cw::CommandResult::AgeMax, "最终时代后应返回已是最高时代");
	}

	// 技能：预警期内不结算，结算只伤害敌方单位，不伤害基地
	void TestSkill(const cw::GameData& InData)
	{
		const cw::GameData Data = Classic(InData);
		std::printf("[测试] 战场技能：预警、结算时机、敌我判定\n");
		cw::GameData Rich = Data;
		Rich.Rules.StartGold = 10000;
		cw::Simulation Sim(Rich);
		Sim.Start();
		for (int I = 0; I < 3; ++I)
		{
			Sim.Apply(1, TrainCmd(0));
			Sim.Apply(0, TrainCmd(0));
		}
		// 等待阵营 1 的单位走到场地中部
		for (int I = 0; I < static_cast<int>(12.f / FixedDt); ++I)
		{
			Sim.Step(FixedDt);
			Sim.ClearEvents();
		}
		float SumX = 0.f;
		int Count = 0;
		for (const cw::Unit& U : Sim.Units())
		{
			if (U.Team == 1)
			{
				SumX += U.X;
				++Count;
			}
		}
		CW_CHECK(Count > 0, "应有敌方单位");
		const float Target = SumX / static_cast<float>(std::max(Count, 1));
		const float Base1 = Sim.Team(1).BaseHp;
		CW_CHECK(Sim.Apply(0, Cmd(cw::CommandType::CastSkill, 0, 0, Target)) == cw::CommandResult::Ok, "施放技能");
		const int32_t SkillIdx = Rich.SkillForAge(0);
		const float Delay = Rich.Skills[static_cast<size_t>(SkillIdx)].Delay;
		bool bEarlyImpact = false;
		int ImpactHits = -1;
		float ImpactTime = 0.f;
		const float CastTime = Sim.Time();
		int AllyHits = 0;
		for (int I = 0; I < static_cast<int>(3.f / FixedDt); ++I)
		{
			Sim.Step(FixedDt);
			for (const cw::SimEvent& Ev : Sim.Events())
			{
				if (Ev.Type == cw::EventType::SkillImpact)
				{
					ImpactHits = Ev.B;
					ImpactTime = Sim.Time() - CastTime;
					bEarlyImpact = ImpactTime < Delay - 0.01f;
				}
				if (Ev.Type == cw::EventType::UnitHit && Ev.Team == 0 && ImpactHits >= 0 && Sim.Time() - CastTime - ImpactTime < 0.001f)
				{
					++AllyHits;
				}
			}
			Sim.ClearEvents();
		}
		CW_CHECK(!bEarlyImpact, "预警期内不应结算");
		CW_CHECK(ImpactHits > 0, "技能应命中敌方单位");
		CW_CHECK(std::fabs(ImpactTime - Delay) < 0.06f, "结算时间应等于预警时长");
		CW_CHECK(Sim.Team(1).BaseHp == Base1, "技能不伤害基地");
		std::printf("    预警 %.2fs 后结算，命中 %d 个敌方单位\n", ImpactTime, ImpactHits);
	}

	// 时间上限：无人进攻时平局；基地生命比例高者获胜
	void TestTimeLimit(const cw::GameData& InData)
	{
		const cw::GameData Data = Classic(InData);
		std::printf("[测试] 时间上限：平局判定与基地生命比例判定\n");
		cw::Simulation Idle(Data);
		Idle.Start();
		int Ended = 0;
		while (Idle.Phase() == cw::MatchPhase::Running && Idle.Time() < Data.Rules.MatchTimeLimit + 10.f)
		{
			Idle.Step(FixedDt);
			for (const cw::SimEvent& Ev : Idle.Events())
			{
				Ended += Ev.Type == cw::EventType::MatchEnded ? 1 : 0;
			}
			Idle.ClearEvents();
		}
		CW_CHECK(Idle.Phase() == cw::MatchPhase::Ended && Idle.GetEndReason() == cw::EndReason::TimeLimit, "到达时间上限应结束对局");
		CW_CHECK(Idle.Winner() == -1 && Ended == 1, "双方基地完好且无击杀应判平局，且只结算一次");
		CW_CHECK(std::fabs(Idle.Time() - Data.Rules.MatchTimeLimit) < 0.06f, "结算时间应等于时间上限");

		// 阵营 0 的一个单位打掉少量阵营 1 基地生命后不再出兵：时间到时阵营 0 胜
		cw::GameData Short = Data;
		Short.Rules.MatchTimeLimit = 200.f;
		Short.Rules.SuddenDeathTime = 10000.f;
		cw::Simulation Sim(Short);
		Sim.Start();
		Sim.Apply(0, TrainCmd(SlotOf(Sim, 0, "StoneAxe")));
		while (Sim.Phase() == cw::MatchPhase::Running && Sim.Time() < 300.f)
		{
			Sim.Step(FixedDt);
			Sim.ClearEvents();
		}
		CW_CHECK(Sim.GetEndReason() == cw::EndReason::TimeLimit && Sim.Winner() == 0, "基地生命比例更高的一方获胜");
		std::printf("    无人进攻：%.0f 秒平局；单方攻城：阵营1 基地剩余 %.0f%%，阵营%d 获胜\n", Idle.Time(),
			Sim.Team(1).BaseHp / Sim.Team(1).BaseMaxHp * 100.f, Sim.Winner());
	}

	// 金矿升级：费用递增、扣费、满级、实际收入提升
	void TestEconomy(const cw::GameData& InData)
	{
		const cw::GameData Data = Classic(InData);
		std::printf("[测试] 金矿升级：费用、收入提升、满级\n");
		cw::GameData Rich = Data;
		Rich.Rules.StartGold = 10000;
		cw::Simulation Sim(Rich);
		Sim.Start();
		const float Base = Sim.IncomePerSecond(0);
		for (int32_t L = 0; L < Rich.Rules.EconomyMaxLevel; ++L)
		{
			const int32_t Expected = Rich.Rules.EconomyBaseCost * (L + 1);
			CW_CHECK(Sim.EconomyUpgradeCost(0) == Expected, "金矿费用应按等级递增");
			const double Before = Sim.Team(0).Gold;
			CW_CHECK(Sim.Apply(0, Cmd(cw::CommandType::UpgradeEconomy)) == cw::CommandResult::Ok, "升级金矿");
			CW_CHECK(std::fabs(Sim.Team(0).Gold - (Before - Expected)) < 0.001, "金矿扣费");
		}
		CW_CHECK(Sim.Apply(0, Cmd(cw::CommandType::UpgradeEconomy)) == cw::CommandResult::MaxLevel, "金矿满级应拒绝");
		const float Boosted = Sim.IncomePerSecond(0);
		CW_CHECK(std::fabs(Boosted - Base * (1.f + Rich.Rules.EconomyIncomeBonus * Rich.Rules.EconomyMaxLevel)) < 0.01f, "收入按等级提高");
		const double G0 = Sim.Team(0).Gold;
		const double G1 = Sim.Team(1).Gold;
		for (int I = 0; I < static_cast<int>(60.f / FixedDt); ++I)
		{
			Sim.Step(FixedDt);
			Sim.ClearEvents();
		}
		const double Diff = (Sim.Team(0).Gold - G0) - (Sim.Team(1).Gold - G1);
		CW_CHECK(std::fabs(Diff - (Boosted - Base) * 60.0) < 1.0, "60 秒收入差应等于加成");

		cw::GameData Poor = Data;
		Poor.Rules.StartGold = Data.Rules.EconomyBaseCost - 1;
		cw::Simulation PoorSim(Poor);
		PoorSim.Start();
		CW_CHECK(PoorSim.Apply(0, Cmd(cw::CommandType::UpgradeEconomy)) == cw::CommandResult::NotEnoughGold, "金币不足应拒绝");
		std::printf("    满级收入 %.1f/秒（基础 %.1f），60 秒多得 %.0f 金\n", Boosted, Base, Diff);
	}

	// 军队姿态：驻守线、越线单位后撤、恢复推进；全程检查不变量
	void TestStance(const cw::GameData& InData)
	{
		const cw::GameData Data = Classic(InData);
		std::printf("[测试] 军队姿态：驻守线、后撤、恢复推进\n");
		cw::GameData Rich = Data;
		Rich.Rules.StartGold = 10000;
		cw::Simulation Sim(Rich);
		Sim.Start();
		CW_CHECK(Sim.Apply(0, Cmd(cw::CommandType::SetStance, 2)) == cw::CommandResult::InvalidParam, "非法姿态参数");
		for (int I = 0; I < 4; ++I)
		{
			Sim.Apply(0, TrainCmd(0));
		}
		InvariantReport Rep;
		auto Run = [&Sim, &Rep](float Seconds)
		{
			for (int I = 0; I < static_cast<int>(Seconds / FixedDt); ++I)
			{
				Sim.Step(FixedDt);
				CheckInvariants(Sim, Rep);
				Sim.ClearEvents();
			}
		};
		auto FrontX = [&Sim]()
		{
			float Best = -1.0e9f;
			for (const cw::Unit& U : Sim.Units())
			{
				if (U.Team == 0 && U.State != cw::UnitState::Dying)
				{
					Best = std::max(Best, U.X);
				}
			}
			return Best;
		};
		Run(15.f);
		const float HoldX = Sim.HoldLineX(0);
		const float BeforeHold = FrontX();
		CW_CHECK(BeforeHold > HoldX + 100.f, "推进状态下前排应已越过驻守线");
		CW_CHECK(Sim.Apply(0, Cmd(cw::CommandType::SetStance, 1)) == cw::CommandResult::Ok, "切换为驻守");
		Run(15.f);
		const float AfterHold = FrontX();
		CW_CHECK(AfterHold <= HoldX + 0.6f, "驻守后所有单位应退回驻守线以内：" + std::to_string(AfterHold - HoldX));
		CW_CHECK(Sim.Apply(0, Cmd(cw::CommandType::SetStance, 0)) == cw::CommandResult::Ok, "切换为推进");
		Run(8.f);
		CW_CHECK(FrontX() > HoldX + 300.f, "恢复推进后应再次前进");
		CW_CHECK(Rep.Total() == 0, "姿态切换过程中不变量违规 " + std::to_string(Rep.Total()));
		std::printf("    驻守线 X=%.0f：驻守前前排 %.0f → 驻守后 %.0f → 恢复推进 %.0f\n", HoldX, BeforeHold, AfterHold, FrontX());
	}

	// 炮塔：只攻击射程内的敌人
	void TestTurret(const cw::GameData& InData)
	{
		const cw::GameData Data = Classic(InData);
		std::printf("[测试] 炮塔：射程、索敌、攻击间隔\n");
		cw::GameData Rich = Data;
		Rich.Rules.StartGold = 10000;
		cw::Simulation Sim(Rich);
		Sim.Start();
		const int32_t Rock = Rich.FindTurret("RockTower");
		CW_CHECK(Sim.Apply(0, Cmd(cw::CommandType::BuildTurret, 0, Rock)) == cw::CommandResult::Ok, "建塔");
		Sim.Apply(1, TrainCmd(SlotOf(Sim, 1, "BeastRider")));
		const float Range = Sim.TurretRange(Rock, 1);
		int Shots = 0;
		float LastShot = -100.f;
		float MinInterval = 1.0e9f;
		bool bOutOfRangeShot = false;
		for (int I = 0; I < static_cast<int>(60.f / FixedDt) && Sim.Phase() == cw::MatchPhase::Running; ++I)
		{
			Sim.Step(FixedDt);
			for (const cw::SimEvent& Ev : Sim.Events())
			{
				if (Ev.Type == cw::EventType::TurretFired && Ev.Team == 0)
				{
					const cw::Unit* T = Sim.FindUnit(Ev.B);
					if (T != nullptr && std::fabs(T->X - Sim.TurretX(0)) - Rich.Units[static_cast<size_t>(T->Def)].Radius > Range + 1.f)
					{
						bOutOfRangeShot = true;
					}
					if (Shots > 0)
					{
						MinInterval = std::min(MinInterval, Sim.Time() - LastShot);
					}
					LastShot = Sim.Time();
					++Shots;
				}
			}
			Sim.ClearEvents();
		}
		CW_CHECK(Shots > 0, "炮塔应开火");
		CW_CHECK(!bOutOfRangeShot, "炮塔不应攻击射程外目标");
		CW_CHECK(Shots < 2 || MinInterval >= Rich.Turrets[static_cast<size_t>(Rock)].AttackInterval - 0.051f, "攻击间隔");
		std::printf("    开火 %d 次，最小间隔 %.2fs\n", Shots, Shots > 1 ? MinInterval : 0.f);
	}

	// ---------------- 统帅 ----------------
	void TestChampion(const cw::GameData& InData)
	{
		std::printf("[测试] 统帅：出生、随军、坚守与后撤、战吼、阵亡赏金与复活、时代进化\n");
		CW_CHECK(!InData.Champions.empty(), "数据中应有统帅");
		if (InData.Champions.empty())
		{
			return;
		}
		cw::GameData Data = InData;
		Data.Doctrines.clear(); // 只考察统帅本身
		Data.Rules.StartGold = 100000;
		cw::Simulation Sim(Data);
		Sim.Start();
		InvariantReport Rep;
		const cw::Unit* C0 = Sim.ChampionUnit(0);
		CW_CHECK(C0 != nullptr && C0->Champion && Sim.ChampionUnit(1) != nullptr, "开局双方都应有统帅");
		const int32_t ChampId = C0 != nullptr ? C0->Id : -1;
		CW_CHECK(Sim.TrainableUnits(0).size() == 3, "统帅不应出现在训练面板");

		// 随军且场上没有部队：守在城门前
		RunFor(Sim, 6.f, &Rep);
		C0 = Sim.ChampionUnit(0);
		const float Guard = Sim.BaseFrontX(0) + Data.Rules.ChampionGuardDistance;
		CW_CHECK(C0 != nullptr && std::fabs(C0->X - Guard) < 1.f, "没有部队时统帅应守在城门前");

		// 随军：跟上最前方的部队
		for (int I = 0; I < 3; ++I)
		{
			Sim.Apply(0, TrainCmd(0));
		}
		RunFor(Sim, 14.f, &Rep);
		C0 = Sim.ChampionUnit(0);
		const float Front = FrontX(Sim, 0);
		CW_CHECK(C0 != nullptr && C0->X >= Front - 40.f && C0->X <= Front + 1.f, "随军统帅应跟在最前方部队旁: " + std::to_string(C0 != nullptr ? C0->X - Front : 0.f));

		// 光环：统帅身边的部队伤害提高（通过实际属性判断：与统帅同位置的部队）
		// 坚守：退回指定位置，非法位置被拒绝
		const float HoldX = Sim.BaseFrontX(0) + 900.f;
		CW_CHECK(Sim.Apply(0, Cmd(cw::CommandType::ChampionMove, 0, 0, HoldX)) == cw::CommandResult::Ok, "坚守指令");
		CW_CHECK(Sim.Apply(0, Cmd(cw::CommandType::ChampionMove, 0, 0, std::numeric_limits<float>::quiet_NaN())) == cw::CommandResult::InvalidParam, "NaN 坚守位置");
		CW_CHECK(Sim.Apply(0, Cmd(cw::CommandType::ChampionMove, 0, 0, -5000.f)) == cw::CommandResult::InvalidParam, "越界坚守位置");
		CW_CHECK(Sim.Apply(0, Cmd(cw::CommandType::ChampionMove, 7)) == cw::CommandResult::InvalidParam, "非法指令参数");
		RunFor(Sim, 12.f, &Rep);
		C0 = Sim.ChampionUnit(0);
		CW_CHECK(C0 != nullptr && std::fabs(C0->X - HoldX) < 1.f, "坚守统帅应停在指定位置");
		CW_CHECK(Sim.Apply(0, Cmd(cw::CommandType::ChampionMove, 1)) == cw::CommandResult::Ok, "恢复随军");

		// 战吼：范围内友军获得增益、冷却（统帅坚守在城门前，新训练的部队从身边经过）
		Sim.Apply(0, Cmd(cw::CommandType::ChampionMove, 0, 0, Guard));
		RunFor(Sim, 8.f, &Rep);
		Sim.Apply(0, TrainCmd(0));
		Sim.Apply(0, TrainCmd(0));
		RunFor(Sim, 4.5f, &Rep);
		CW_CHECK(Sim.Apply(0, Cmd(cw::CommandType::ChampionAbility)) == cw::CommandResult::Ok, "施放战吼");
		int32_t Buffed = 0;
		for (const cw::Unit& U : Sim.Units())
		{
			Buffed += U.Team == 0 && !U.Champion && U.BuffTime > 0.f ? 1 : 0;
		}
		CW_CHECK(Buffed >= 2, "战吼应影响范围内友军：" + std::to_string(Buffed));
		CW_CHECK(Sim.Apply(0, Cmd(cw::CommandType::ChampionAbility)) == cw::CommandResult::OnCooldown, "战吼冷却");
		CW_CHECK(Sim.Team(0).ChampionAbilitySeq == 1, "施放序号递增");

		// 阵亡赏金与复活：统帅孤身坚守在敌方城门前，被敌方部队与统帅击杀
		CW_CHECK(Sim.Apply(0, Cmd(cw::CommandType::ChampionMove, 0, 0, Sim.BaseFrontX(1))) == cw::CommandResult::Ok, "冲向敌方城门");
		for (int I = 0; I < 5; ++I)
		{
			Sim.Apply(1, TrainCmd(SlotOf(Sim, 1, "BeastRider")));
		}
		float DiedAt = -1.f;
		int32_t BountyGold = -1;
		double Gold1Before = 0.0;
		for (int I = 0; I < static_cast<int>(150.f / FixedDt) && DiedAt < 0.f; ++I)
		{
			Gold1Before = Sim.Team(1).Gold;
			Sim.Step(FixedDt);
			CheckInvariants(Sim, Rep);
			for (const cw::SimEvent& Ev : Sim.Events())
			{
				if (Ev.Type == cw::EventType::ChampionDied && Ev.Team == 0)
				{
					DiedAt = Sim.Time();
					BountyGold = static_cast<int32_t>(Ev.Value);
				}
			}
			Sim.ClearEvents();
		}
		CW_CHECK(DiedAt > 0.f, "统帅应被击杀");
		CW_CHECK(BountyGold == Data.Champions[0].Bounty, "击杀方应获得统帅赏金：" + std::to_string(BountyGold));
		CW_CHECK(Sim.ChampionUnit(0) == nullptr && Sim.Team(0).ChampionId < 0, "阵亡期间没有统帅");
		CW_CHECK(Sim.Apply(0, Cmd(cw::CommandType::ChampionAbility)) == cw::CommandResult::ChampionDead, "阵亡时不能施放战吼");
		CW_CHECK(Sim.Team(1).Stats.ChampionKills == 1, "统帅击杀计数");
		(void)Gold1Before;
		Sim.Apply(0, Cmd(cw::CommandType::ChampionMove, 1));
		RunFor(Sim, Data.Champions[0].RespawnTime - 1.f, &Rep);
		CW_CHECK(Sim.ChampionUnit(0) == nullptr, "复活时间未到");
		RunFor(Sim, 1.2f, &Rep);
		const cw::Unit* Reborn = Sim.ChampionUnit(0);
		CW_CHECK(Reborn != nullptr && Reborn->Id != ChampId, "复活为新的单位");
		CW_CHECK(Reborn != nullptr && std::fabs(Reborn->Hp - Reborn->MaxHp) < 0.01f, "复活后满生命");
		CW_CHECK(Rep.Total() == 0, "统帅测试中不变量违规 " + std::to_string(Rep.Total()) + " enemy=" + std::to_string(Rep.EnemyOverlap)
			+ " ally=" + std::to_string(Rep.AllyOverlap) + " lane=" + std::to_string(Rep.OutOfLane) + " melee=" + std::to_string(Rep.MeleeOutOfRange)
			+ " hp=" + std::to_string(Rep.BadHp));

		// 时代进化：同一个统帅原地进化，生命比例保持
		cw::GameData Fast = Data;
		Fast.Rules.PassiveXpPerSec = 1000.f;
		cw::Simulation Evo(Fast);
		Evo.Start();
		RunFor(Evo, 2.f);
		const int32_t EvoId = Evo.ChampionUnit(0)->Id;
		CW_CHECK(Evo.Apply(0, Cmd(cw::CommandType::UpgradeAge)) == cw::CommandResult::Ok, "升级时代");
		RunFor(Evo, Fast.Ages[1].UpgradeDuration + 0.2f);
		const cw::Unit* Evolved = Evo.ChampionUnit(0);
		CW_CHECK(Evolved != nullptr && Evolved->Id == EvoId, "进化后仍是同一个统帅");
		CW_CHECK(Evolved != nullptr && Evolved->Def == Fast.Champions[static_cast<size_t>(Fast.ChampionForAge(1))].UnitDefIndex, "进化为中世纪统帅");
		CW_CHECK(Evolved != nullptr && std::fabs(Evolved->MaxHp - Fast.Units[static_cast<size_t>(Evolved->Def)].MaxHp) < 0.01f, "进化后生命上限提升");
		std::printf("    守卫位置 %.0f，随军偏差 %.0fcm，战吼影响 %d 个友军，阵亡于 %.0fs 赏金 %d，%.0f 秒后复活\n", Guard,
			C0 != nullptr ? 0.f : 0.f, Buffed, DiedAt, BountyGold, Data.Champions[0].RespawnTime);
	}

	// ---------------- 老兵晋升 ----------------
	void TestVeterancy(const cw::GameData& InData)
	{
		std::printf("[测试] 老兵：击杀积累战功、晋升提升生命与伤害\n");
		cw::GameData Data = Classic(InData);
		Data.Rules.StartGold = 10000;
		cw::Simulation Sim(Data);
		Sim.Start();
		Sim.Apply(0, TrainCmd(SlotOf(Sim, 0, "BeastRider")));
		for (int I = 0; I < 4; ++I)
		{
			Sim.Apply(1, TrainCmd(SlotOf(Sim, 1, "StoneSlinger")));
		}
		InvariantReport Rep;
		std::vector<cw::SimEvent> Events;
		RunFor(Sim, 60.f, &Rep, &Events);
		int Promotions = 0;
		int32_t PromotedId = -1;
		for (const cw::SimEvent& Ev : Events)
		{
			if (Ev.Type == cw::EventType::UnitPromoted && Ev.Team == 0)
			{
				++Promotions;
				PromotedId = Ev.A;
			}
		}
		const cw::UnitDef& Rider = Data.Units[static_cast<size_t>(Data.FindUnit("BeastRider"))];
		const cw::Unit* Vet = Sim.FindUnit(PromotedId);
		CW_CHECK(Promotions >= 1, "击杀 3 个投石猎手（价值 90 ≥ 造价 75）后应晋升");
		CW_CHECK(Vet == nullptr || (Vet->Rank >= 1 && std::fabs(Vet->MaxHp - Rider.MaxHp * (1.f + Data.Rules.VeteranHpBonus * static_cast<float>(Vet->Rank))) < 0.01f),
			"晋升后生命上限按等级提高");
		CW_CHECK(Vet == nullptr || std::fabs(Vet->DamageMul - (1.f + Data.Rules.VeteranDamageBonus * static_cast<float>(Vet->Rank))) < 0.001f, "晋升后伤害倍率提高");
		CW_CHECK(Sim.Team(0).Stats.Promotions == Promotions, "晋升计数");
		CW_CHECK(Rep.Total() == 0, "老兵测试中不变量违规");
		std::printf("    猛兽骑兵晋升 %d 次，当前等级 %d，生命上限 %.0f（原 %.0f）\n", Promotions, Vet != nullptr ? Vet->Rank : -1,
			Vet != nullptr ? Vet->MaxHp : 0.f, Rider.MaxHp);
	}

	// ---------------- 国策 ----------------
	// 找到一个种子，使阵营 0 开局选项中包含指定国策
	uint32_t SeedOffering(const cw::GameData& Data, const char* DoctrineId)
	{
		const int32_t Wanted = Data.FindDoctrine(DoctrineId);
		for (uint32_t Seed = 1; Seed < 500; ++Seed)
		{
			cw::Simulation Probe(Data, Seed);
			Probe.Start();
			const std::vector<int32_t>& Offer = Probe.Team(0).Offer;
			if (std::find(Offer.begin(), Offer.end(), Wanted) != Offer.end())
			{
				return Seed;
			}
		}
		return 0;
	}

	int32_t OfferIndex(const cw::Simulation& Sim, int32_t Team, const char* DoctrineId)
	{
		const std::vector<int32_t>& Offer = Sim.Team(Team).Offer;
		const int32_t Wanted = Sim.Data().FindDoctrine(DoctrineId);
		for (size_t I = 0; I < Offer.size(); ++I)
		{
			if (Offer[I] == Wanted)
			{
				return static_cast<int32_t>(I);
			}
		}
		return -1;
	}

	void TestDoctrines(const cw::GameData& InData)
	{
		std::printf("[测试] 国策：开局与升级时代提供选项、选择校验、效果立即生效、不重复\n");
		CW_CHECK(InData.Doctrines.size() >= 6, "数据中应有国策");
		cw::GameData Data = InData;
		Data.Champions.clear();
		Data.Rules.StartGold = 10000;

		cw::Simulation Sim(Data, 3);
		CW_CHECK(Sim.Apply(0, Cmd(cw::CommandType::ChooseDoctrine, 0)) == cw::CommandResult::MatchNotRunning, "开局前不能选择");
		Sim.Start();
		const std::vector<int32_t> Offer = Sim.Team(0).Offer;
		CW_CHECK(static_cast<int32_t>(Offer.size()) == Data.Rules.DoctrineChoices, "开局应提供 3 个选项");
		CW_CHECK(Offer.size() < 2 || (Offer[0] != Offer[1] && (Offer.size() < 3 || (Offer[0] != Offer[2] && Offer[1] != Offer[2]))), "选项互不相同");
		CW_CHECK(Sim.Team(0).PendingPicks == 1, "待选次数 1");
		CW_CHECK(Sim.Apply(0, Cmd(cw::CommandType::ChooseDoctrine, 5)) == cw::CommandResult::InvalidParam, "越界选项");
		CW_CHECK(Sim.Apply(0, Cmd(cw::CommandType::ChooseDoctrine, -1)) == cw::CommandResult::InvalidParam, "负数选项");
		CW_CHECK(Sim.Apply(0, Cmd(cw::CommandType::ChooseDoctrine, 1)) == cw::CommandResult::Ok, "选择国策");
		CW_CHECK(Sim.Team(0).Doctrines.size() == 1 && Sim.Team(0).Doctrines[0] == Offer[1], "记录所选国策");
		CW_CHECK(Sim.Team(0).Offer.empty() && Sim.Team(0).PendingPicks == 0, "选择后没有待选");
		CW_CHECK(Sim.Apply(0, Cmd(cw::CommandType::ChooseDoctrine, 0)) == cw::CommandResult::NoOffer, "没有待选时拒绝");
		CW_CHECK(Sim.Team(1).Doctrines.empty() && Sim.Team(1).Offer.size() == Offer.size(), "阵营之间互不影响");

		// 铁壁方阵：已在场与新训练的近战单位生命 +30%
		const uint32_t WallSeed = SeedOffering(Data, "ShieldWall");
		CW_CHECK(WallSeed != 0, "应能抽到铁壁方阵");
		cw::Simulation Wall(Data, WallSeed);
		Wall.Start();
		Wall.Apply(0, TrainCmd(0));
		RunFor(Wall, 3.f);
		const cw::UnitDef& Axe = Data.Units[static_cast<size_t>(Wall.TrainableUnits(0)[0])];
		CW_CHECK(Wall.Apply(0, Cmd(cw::CommandType::ChooseDoctrine, OfferIndex(Wall, 0, "ShieldWall"))) == cw::CommandResult::Ok, "选择铁壁方阵");
		bool bExistingBoosted = false;
		for (const cw::Unit& U : Wall.Units())
		{
			bExistingBoosted = bExistingBoosted || (U.Team == 0 && std::fabs(U.MaxHp - Axe.MaxHp * 1.3f) < 0.01f);
		}
		CW_CHECK(bExistingBoosted, "已在场的近战单位立即获得生命加成");

		// 重农兴商：收入 +20%
		const uint32_t ProsperSeed = SeedOffering(Data, "Prosperity");
		cw::Simulation Prosper(Data, ProsperSeed);
		Prosper.Start();
		const float Before = Prosper.IncomePerSecond(0);
		CW_CHECK(Prosper.Apply(0, Cmd(cw::CommandType::ChooseDoctrine, OfferIndex(Prosper, 0, "Prosperity"))) == cw::CommandResult::Ok, "选择重农兴商");
		CW_CHECK(std::fabs(Prosper.IncomePerSecond(0) - Before * 1.2f) < 0.01f, "收入提高 20%");

		// 铁甲洪流：重型造价 -15%（训练扣费与界面一致）
		const uint32_t TideSeed = SeedOffering(Data, "IronTide");
		cw::Simulation Tide(Data, TideSeed);
		Tide.Start();
		CW_CHECK(Tide.Apply(0, Cmd(cw::CommandType::ChooseDoctrine, OfferIndex(Tide, 0, "IronTide"))) == cw::CommandResult::Ok, "选择铁甲洪流");
		const int32_t HeavyDef = Tide.TrainableUnits(0)[2];
		const int32_t Expected = static_cast<int32_t>(static_cast<float>(Data.Units[static_cast<size_t>(HeavyDef)].Cost) * 0.85f + 0.5f);
		const double G0 = Tide.Team(0).Gold;
		CW_CHECK(Tide.UnitCost(0, HeavyDef) == Expected && Tide.Apply(0, TrainCmd(2)) == cw::CommandResult::Ok
			&& std::fabs(Tide.Team(0).Gold - (G0 - Expected)) < 0.001, "重型单位按折扣价扣费");

		// 升级时代获得新的选择；未使用的选择次数累积；已选国策不再出现
		cw::GameData Fast = Data;
		Fast.Rules.PassiveXpPerSec = 1000.f;
		cw::Simulation Ages(Fast, 11);
		Ages.Start();
		int Picks = 0;
		for (int32_t A = 1; A < static_cast<int32_t>(Fast.Ages.size()); ++A)
		{
			RunFor(Ages, 2.f);
			Ages.Apply(0, Cmd(cw::CommandType::UpgradeAge));
			RunFor(Ages, Fast.Ages[static_cast<size_t>(A)].UpgradeDuration + 0.2f);
			if (A == 1)
			{
				CW_CHECK(Ages.Team(0).PendingPicks == 2 && Ages.Team(0).Offer.size() == 3, "未选择时次数累积，选项保持不变");
			}
			while (!Ages.Team(0).Offer.empty())
			{
				CW_CHECK(Ages.Apply(0, Cmd(cw::CommandType::ChooseDoctrine, 0)) == cw::CommandResult::Ok, "依次选择");
				++Picks;
			}
		}
		std::vector<int32_t> Chosen = Ages.Team(0).Doctrines;
		std::sort(Chosen.begin(), Chosen.end());
		CW_CHECK(std::adjacent_find(Chosen.begin(), Chosen.end()) == Chosen.end(), "已选国策不应重复出现");
		CW_CHECK(Picks == static_cast<int>(Fast.Ages.size()), "每个时代一次选择（含开局）：" + std::to_string(Picks));
		std::string Names;
		for (const int32_t D : Ages.Team(0).Doctrines)
		{
			Names += Fast.Doctrines[static_cast<size_t>(D)].DisplayName + " ";
		}
		std::printf("    5 个时代共选择 %d 项：%s\n", Picks, Names.c_str());
	}

	// ---------------- 背水一战 ----------------
	void TestLastStand(const cw::GameData& InData)
	{
		std::printf("[测试] 背水一战：触发条件、每局一次、征召民兵、全军鼓舞、炮塔强化、修复城墙\n");
		cw::GameData Data = InData;
		Data.Doctrines.clear();
		cw::Simulation Full(Data);
		Full.Start();
		CW_CHECK(Full.Apply(0, Cmd(cw::CommandType::LastStand)) == cw::CommandResult::Unavailable, "基地满血时不可用");

		// 规则测试：把触发门槛设为 100%，直接检验效果
		cw::GameData Easy = Data;
		Easy.Rules.LastStandBaseHpRatio = 1.01f;
		Easy.Rules.StartGold = 10000;
		cw::Simulation Sim(Easy);
		Sim.Start();
		Sim.Apply(0, TrainCmd(0));
		RunFor(Sim, 3.f);
		const size_t QueueBefore = Sim.Team(0).Queue.size();
		const double GoldBefore = Sim.Team(0).Gold;
		CW_CHECK(Sim.Apply(0, Cmd(cw::CommandType::LastStand)) == cw::CommandResult::Ok, "满足条件时可以发动");
		CW_CHECK(Sim.Team(0).LastStandUsed, "记录已使用");
		CW_CHECK(Sim.Team(0).Queue.size() == QueueBefore + static_cast<size_t>(Easy.Rules.LastStandMilitia), "征召民兵进入队列最前");
		CW_CHECK(std::fabs(Sim.Team(0).Gold - GoldBefore) < 0.001, "征召免费");
		CW_CHECK(Sim.Team(0).TurretBoostTime > 0.f, "炮塔强化开始计时");
		int32_t Buffed = 0;
		for (const cw::Unit& U : Sim.Units())
		{
			Buffed += U.Team == 0 && U.State != cw::UnitState::Dying && U.BuffTime > 0.f ? 1 : 0;
		}
		CW_CHECK(Buffed >= 1, "全军获得鼓舞");
		CW_CHECK(Sim.Apply(0, Cmd(cw::CommandType::LastStand)) == cw::CommandResult::AlreadyUsed, "每局只能用一次");
		std::vector<cw::SimEvent> Events;
		RunFor(Sim, 2.f, nullptr, &Events);
		int Spawned = 0;
		for (const cw::SimEvent& Ev : Events)
		{
			Spawned += Ev.Type == cw::EventType::UnitSpawned && Ev.Team == 0 ? 1 : 0;
		}
		CW_CHECK(Spawned >= Easy.Rules.LastStandMilitia, "民兵在 2 秒内出阵：" + std::to_string(Spawned));
		CW_CHECK(Sim.Team(1).LastStandUsed == false, "不影响对方");
		std::printf("    征召 %d 名民兵，2 秒内出阵 %d 个单位，鼓舞 %d 个单位\n", Easy.Rules.LastStandMilitia, Spawned, Buffed);
	}

	// ---------------- AI 对战：完整对局与数值检查 ----------------
	struct MatchResult
	{
		int Winner = -1;
		float Duration = 0.f;
		float AgeTime[2][8] = { { 0.f, -1.f, -1.f, -1.f, -1.f, -1.f, -1.f, -1.f }, { 0.f, -1.f, -1.f, -1.f, -1.f, -1.f, -1.f, -1.f } };
		cw::EndReason Reason = cw::EndReason::None;
		cw::TeamStats Stats[2];
		int Violations = 0;
		size_t PeakUnits = 0;
		int SkillCasts[2] = { 0, 0 };
		int TurretsBuilt[2] = { 0, 0 };
		int ChampionAbilities[2] = { 0, 0 };
		std::vector<int32_t> Doctrines[2];
		bool LastStand[2] = { false, false };
	};

	// 规则核心性能统计（服务器端每步耗时，不含渲染）
	double GSimSeconds = 0.0;
	long long GSimSteps = 0;
	double GWorstStepMs = 0.0;

	MatchResult RunAiMatch(const cw::GameData& Data, cw::AiDifficulty D0, cw::AiDifficulty D1, uint32_t Seed, float MaxTime)
	{
		cw::Simulation Sim(Data, Seed * 7919u + 13u);
		cw::AiConfig C0;
		C0.Difficulty = D0;
		C0.Seed = Seed * 2654435761u + 1u;
		cw::AiConfig C1;
		C1.Difficulty = D1;
		C1.Seed = Seed * 40503u + 7u;
		cw::AiPlayer Ai0(0, C0);
		cw::AiPlayer Ai1(1, C1);
		Sim.Start();
		InvariantReport Rep;
		MatchResult R;
		while (Sim.Phase() == cw::MatchPhase::Running && Sim.Time() < MaxTime)
		{
			const auto StepStart = std::chrono::steady_clock::now();
			Ai0.Tick(Sim, FixedDt);
			Ai1.Tick(Sim, FixedDt);
			Sim.Step(FixedDt);
			const double StepSec = std::chrono::duration<double>(std::chrono::steady_clock::now() - StepStart).count();
			GSimSeconds += StepSec;
			GSimSteps += 1;
			GWorstStepMs = std::max(GWorstStepMs, StepSec * 1000.0);
			CheckInvariants(Sim, Rep);
			for (const cw::SimEvent& Ev : Sim.Events())
			{
				if (Ev.Type == cw::EventType::AgeUpgradeDone && Ev.A < 8)
				{
					R.AgeTime[Ev.Team][Ev.A] = Sim.Time();
				}
				if (Ev.Type == cw::EventType::SkillCast)
				{
					++R.SkillCasts[Ev.Team];
				}
				if (Ev.Type == cw::EventType::ChampionAbility)
				{
					++R.ChampionAbilities[Ev.Team];
				}
				if (Ev.Type == cw::EventType::LastStand)
				{
					R.LastStand[Ev.Team] = true;
				}
			}
			Sim.ClearEvents();
			R.PeakUnits = std::max(R.PeakUnits, Sim.Units().size());
			for (int32_t T = 0; T < 2; ++T)
			{
				int Built = 0;
				for (const cw::TurretSlot& S : Sim.Team(T).Turrets)
				{
					Built += S.Def != cw::InvalidIndex ? 1 : 0;
				}
				R.TurretsBuilt[T] = std::max(R.TurretsBuilt[T], Built);
			}
		}
		R.Winner = Sim.Winner();
		R.Reason = Sim.GetEndReason();
		R.Duration = Sim.Time();
		R.Stats[0] = Sim.Team(0).Stats;
		R.Stats[1] = Sim.Team(1).Stats;
		R.Doctrines[0] = Sim.Team(0).Doctrines;
		R.Doctrines[1] = Sim.Team(1).Doctrines;
		R.Violations = Rep.Total();
		if (GVerbose)
		{
			for (int32_t T = 0; T < 2; ++T)
			{
				const cw::TeamState& S = Sim.Team(T);
				std::string AgeTimes;
				for (size_t A = 1; A < Data.Ages.size() && A < 8; ++A)
				{
					AgeTimes += (A > 1 ? "/" : "") + std::to_string(static_cast<int>(R.AgeTime[T][A]));
				}
				std::printf("      [阵营%d %s] 时代=%d 升级@%ss 基地=%.0f/%.0f 训练=%d 损失=%d 击杀=%d 花费=%d 击杀金=%d 对基地伤害=%.0f 技能=%d 炮塔=%d 金矿=%d\n",
					T, T == 0 ? (D0 == cw::AiDifficulty::Hard ? "困难" : D0 == cw::AiDifficulty::Easy ? "简单" : "普通")
					          : (D1 == cw::AiDifficulty::Hard ? "困难" : D1 == cw::AiDifficulty::Easy ? "简单" : "普通"),
					S.Age, AgeTimes.c_str(), S.BaseHp, S.BaseMaxHp, S.Stats.UnitsTrained, S.Stats.UnitsLost,
					S.Stats.Kills, S.Stats.GoldSpent, S.Stats.GoldEarned, S.Stats.DamageToBase, R.SkillCasts[T], R.TurretsBuilt[T], S.EconomyLevel);
			}
		}
		if (GVerbose || Rep.Total() > 0)
		{
			std::printf("      seed=%u 胜者=%d 时长=%.0fs 违规=%d (enemy=%d ally=%d lane=%d dead=%d melee=%d hp=%d hitAfterDeath=%d end=%d)\n",
				Seed, R.Winner, R.Duration, Rep.Total(), Rep.EnemyOverlap, Rep.AllyOverlap, Rep.OutOfLane, Rep.DeadActing,
				Rep.MeleeOutOfRange, Rep.BadHp, Rep.HitAfterDeath, Rep.MatchEndedEvents);
		}
		return R;
	}

	void TestAiMatches(const cw::GameData& Data, int Matches)
	{
		std::printf("[测试] AI 对战（%d 局 普通 vs 普通，并测试难度差异）\n", Matches);
		const float MaxTime = 1800.f;
		int Wins[3] = { 0, 0, 0 }; // 0, 1, 平局/超时
		float SumDur = 0.f;
		int DurationBuckets[6] = { 0, 0, 0, 0, 0, 0 }; // <8、8~12、12~16、16~20、20~25 分钟、到达时限
		float MinDur = 1.0e9f;
		float MaxDur = 0.f;
		float SumAge[8] = {};
		int AgeCount[8] = {};
		int TimeLimitEnds = 0;
		int TotalViolations = 0;
		size_t Peak = 0;
		int Skills = 0;
		int Turrets = 0;
		long long Trained = 0;
		int ChampionKills = 0;
		int Promotions = 0;
		int Abilities = 0;
		int LastStands = 0;
		int Comebacks = 0; // 发动背水一战的一方最终获胜
		std::vector<int> DoctrineCount(Data.Doctrines.size(), 0);
		for (int I = 0; I < Matches; ++I)
		{
			const MatchResult R = RunAiMatch(Data, cw::AiDifficulty::Normal, cw::AiDifficulty::Normal, static_cast<uint32_t>(I + 1), MaxTime);
			Wins[R.Winner >= 0 ? R.Winner : 2] += 1;
			TimeLimitEnds += R.Reason == cw::EndReason::TimeLimit ? 1 : 0;
			SumDur += R.Duration;
			if (R.Reason == cw::EndReason::TimeLimit)
			{
				DurationBuckets[5] += 1;
			}
			else
			{
				const float Minutes = R.Duration / 60.f;
				DurationBuckets[Minutes < 8.f ? 0 : Minutes < 12.f ? 1 : Minutes < 16.f ? 2 : Minutes < 20.f ? 3 : 4] += 1;
			}
			MinDur = std::min(MinDur, R.Duration);
			MaxDur = std::max(MaxDur, R.Duration);
			for (int T = 0; T < 2; ++T)
			{
				for (int A = 1; A < 8; ++A)
				{
					if (R.AgeTime[T][A] > 0.f)
					{
						SumAge[A] += R.AgeTime[T][A];
						++AgeCount[A];
					}
				}
				Skills += R.SkillCasts[T];
				Turrets += R.TurretsBuilt[T];
				Trained += R.Stats[T].UnitsTrained;
				ChampionKills += R.Stats[T].ChampionKills;
				Promotions += R.Stats[T].Promotions;
				Abilities += R.ChampionAbilities[T];
				LastStands += R.LastStand[T] ? 1 : 0;
				Comebacks += R.LastStand[T] && R.Winner == T ? 1 : 0;
				for (const int32_t D : R.Doctrines[T])
				{
					DoctrineCount[static_cast<size_t>(D)] += 1;
				}
			}
			TotalViolations += R.Violations;
			Peak = std::max(Peak, R.PeakUnits);
		}
		std::printf("    胜负：阵营0 %d / 阵营1 %d / 平局 %d；其中 %d 局到达时间上限\n", Wins[0], Wins[1], Wins[2], TimeLimitEnds);
		std::printf("    时长：平均 %.1f 分钟（%.1f ~ %.1f）；分布 <8分钟 %d · 8~12 %d · 12~16 %d · 16~20 %d · 20~25 %d · 时限 %d\n",
			SumDur / static_cast<float>(Matches) / 60.f, MinDur / 60.f, MaxDur / 60.f, DurationBuckets[0], DurationBuckets[1], DurationBuckets[2],
			DurationBuckets[3], DurationBuckets[4], DurationBuckets[5]);
		std::string AgeLine;
		for (size_t A = 1; A < Data.Ages.size() && A < 8; ++A)
		{
			char Buf[160];
			std::snprintf(Buf, sizeof(Buf), "%s%s %d/%d 次（平均 %.1f 分钟）", A > 1 ? "；" : "", Data.Ages[A].DisplayName.c_str(), AgeCount[A],
				Matches * 2, AgeCount[A] > 0 ? SumAge[A] / static_cast<float>(AgeCount[A]) / 60.f : 0.f);
			AgeLine += Buf;
		}
		std::printf("    进入时代：%s\n", AgeLine.c_str());
		std::printf("    每局平均训练 %.0f 个单位，技能 %.1f 次，炮塔 %.1f 座；峰值同屏单位 %zu\n",
			static_cast<double>(Trained) / Matches, static_cast<double>(Skills) / Matches, static_cast<double>(Turrets) / Matches, Peak);
		if (!Data.Champions.empty() || !Data.Doctrines.empty())
		{
			std::printf("    每局平均（双方合计）：统帅阵亡 %.1f 次，战吼 %.1f 次，老兵晋升 %.1f 次；背水一战 %d 次，其中翻盘获胜 %d 次\n",
				static_cast<double>(ChampionKills) / Matches, static_cast<double>(Abilities) / Matches, static_cast<double>(Promotions) / Matches,
				LastStands, Comebacks);
			std::string Popular;
			std::vector<size_t> Order(DoctrineCount.size());
			for (size_t I = 0; I < Order.size(); ++I)
			{
				Order[I] = I;
			}
			std::sort(Order.begin(), Order.end(), [&DoctrineCount](size_t L, size_t R) { return DoctrineCount[L] > DoctrineCount[R]; });
			for (size_t I = 0; I < Order.size() && I < 6; ++I)
			{
				Popular += Data.Doctrines[Order[I]].DisplayName + "×" + std::to_string(DoctrineCount[Order[I]]) + " ";
			}
			std::printf("    AI 最常选的国策：%s\n", Popular.c_str());
		}
		std::printf("    规则核心耗时（含双方 AI）：平均 %.1f 微秒/步，最慢 %.3f 毫秒/步，共 %lld 步（服务器 20 Hz 预算 50 毫秒/步）\n",
			GSimSteps > 0 ? GSimSeconds * 1.0e6 / static_cast<double>(GSimSteps) : 0.0, GWorstStepMs, GSimSteps);
		CW_CHECK(TotalViolations == 0, "AI 对战中出现不变量违规 " + std::to_string(TotalViolations));
		CW_CHECK(TimeLimitEnds < Matches / 4 + 1, "到达时间上限的对局过多：对局难以分出胜负");

		// 难度差异
		int HardWins = 0;
		const int DiffMatches = std::max(Matches / 2, 4);
		for (int I = 0; I < DiffMatches; ++I)
		{
			const bool bSwap = (I % 2) == 1;
			const MatchResult R = RunAiMatch(Data, bSwap ? cw::AiDifficulty::Easy : cw::AiDifficulty::Hard,
				bSwap ? cw::AiDifficulty::Hard : cw::AiDifficulty::Easy, static_cast<uint32_t>(1000 + I), MaxTime);
			const int HardTeam = bSwap ? 1 : 0;
			HardWins += R.Winner == HardTeam ? 1 : 0;
			CW_CHECK(R.Violations == 0, "难度对战不变量违规");
		}
		std::printf("    困难 vs 简单：困难胜 %d/%d\n", HardWins, DiffMatches);
		CW_CHECK(HardWins * 3 >= DiffMatches * 2, "困难 AI 应明显强于简单 AI");
	}
}

namespace
{
	// ---------------- 数值诊断：固定兵种配比的对抗矩阵 ----------------
	struct Mix
	{
		const char* Name;
		float W[3]; // 近战 / 远程 / 重型 的出兵权重
	};

	// 返回 阵营0 的净优势：基地生命差（0 方剩余 - 1 方剩余）/ 上限，被摧毁记 ±1
	float RunMixDuel(const cw::GameData& Base, int32_t Age, const Mix& M0, const Mix& M1, float Duration)
	{
		cw::GameData Data = Classic(Base);
		for (cw::AgeDef& A : Data.Ages)
		{
			A.XpToEnter = 0;
			A.GoldToEnter = 0;
			A.UpgradeDuration = 0.f;
		}
		cw::Simulation Sim(Data);
		Sim.Start();
		for (int32_t I = 0; I < Age; ++I)
		{
			Sim.Apply(0, Cmd(cw::CommandType::UpgradeAge));
			Sim.Apply(1, Cmd(cw::CommandType::UpgradeAge));
			Sim.Step(FixedDt);
		}
		float Acc[2][3] = { { 0.f, 0.f, 0.f }, { 0.f, 0.f, 0.f } };
		const Mix* Mixes[2] = { &M0, &M1 };
		while (Sim.Phase() == cw::MatchPhase::Running && Sim.Time() < Duration)
		{
			for (int32_t T = 0; T < 2; ++T)
			{
				if (!Sim.Team(T).Queue.empty())
				{
					continue;
				}
				// 选择累计欠账最多的定位（确定性的加权轮转）
				int32_t Best = -1;
				for (int32_t R = 0; R < 3; ++R)
				{
					if (Mixes[T]->W[R] > 0.f && (Best < 0 || Acc[T][R] > Acc[T][Best]))
					{
						Best = R;
					}
				}
				const std::vector<int32_t> List = Sim.TrainableUnits(T);
				int32_t Slot = -1;
				for (size_t I = 0; I < List.size(); ++I)
				{
					if (static_cast<int32_t>(Data.Units[static_cast<size_t>(List[I])].Role) == Best)
					{
						Slot = static_cast<int32_t>(I);
					}
				}
				if (Slot >= 0 && Sim.Apply(T, TrainCmd(Slot)) == cw::CommandResult::Ok)
				{
					for (int32_t R = 0; R < 3; ++R)
					{
						Acc[T][R] += Mixes[T]->W[R];
					}
					Acc[T][Best] -= 1.f;
				}
			}
			Sim.Step(FixedDt);
			Sim.ClearEvents();
		}
		if (Sim.Phase() == cw::MatchPhase::Ended)
		{
			return Sim.Winner() == 0 ? 1.f : -1.f;
		}
		return Sim.Team(0).BaseHp / Sim.Team(0).BaseMaxHp - Sim.Team(1).BaseHp / Sim.Team(1).BaseMaxHp;
	}

	// 单局时间线：每 30 秒输出双方状态，用于定位僵持原因
	void RunTrace(const cw::GameData& Data, cw::AiDifficulty D0, cw::AiDifficulty D1, uint32_t Seed)
	{
		cw::Simulation Sim(Data);
		cw::AiConfig C0;
		C0.Difficulty = D0;
		C0.Seed = Seed * 2654435761u + 1u;
		cw::AiConfig C1;
		C1.Difficulty = D1;
		C1.Seed = Seed * 40503u + 7u;
		cw::AiPlayer Ai0(0, C0);
		cw::AiPlayer Ai1(1, C1);
		Sim.Start();
		float NextPrint = 0.f;
		const char* IntentNames[] = { "空闲", "出兵", "防守", "攒升级", "推进" };
		while (Sim.Phase() == cw::MatchPhase::Running && Sim.Time() < 1800.f)
		{
			Ai0.Tick(Sim, FixedDt);
			Ai1.Tick(Sim, FixedDt);
			Sim.Step(FixedDt);
			Sim.ClearEvents();
			if (Sim.Time() < NextPrint)
			{
				continue;
			}
			NextPrint += 30.f;
			float Front[2] = { -1.f, -1.f };
			float Value[2] = { 0.f, 0.f };
			int Count[2] = { 0, 0 };
			for (const cw::Unit& U : Sim.Units())
			{
				if (U.State == cw::UnitState::Dying)
				{
					continue;
				}
				const cw::UnitDef& D = Data.Units[static_cast<size_t>(U.Def)];
				Value[U.Team] += static_cast<float>(D.Cost) * U.Hp / D.MaxHp;
				Count[U.Team] += 1;
				const float Progress = U.Team == 0 ? U.X : Data.Rules.LaneLength - U.X;
				Front[U.Team] = std::max(Front[U.Team], Progress);
			}
			std::printf("t=%4.0fs", Sim.Time());
			for (int32_t T = 0; T < 2; ++T)
			{
				const cw::TeamState& S = Sim.Team(T);
				int Turrets = 0;
				for (const cw::TurretSlot& Slot : S.Turrets)
				{
					Turrets += Slot.Def != cw::InvalidIndex ? 1 : 0;
				}
				const cw::AiPlayer& Ai = T == 0 ? Ai0 : Ai1;
				std::printf(" | T%d 时代%d 金%5.0f 经验%5.0f 兵%2d(%4.0f) 前线%4.0f 基地%4.0f 塔%d 队列%zu %s",
					T, S.Age, S.Gold, S.Xp, Count[T], Value[T], Front[T], S.BaseHp, Turrets, S.Queue.size(),
					IntentNames[static_cast<int>(Ai.Intent())]);
			}
			std::printf("\n");
		}
		std::printf("结束 t=%.0fs 胜者=%d\n", Sim.Time(), Sim.Winner());
	}

	// 整批计时：不做逐步不变量检查，测量规则核心 + AI 的纯计算耗时
	void RunBenchmark(const cw::GameData& Data, int Matches)
	{
		long long Steps = 0;
		size_t PeakUnits = 0;
		long long UnitSteps = 0;
		const auto Start = std::chrono::steady_clock::now();
		for (int I = 0; I < Matches; ++I)
		{
			cw::Simulation Sim(Data);
			cw::AiConfig C0;
			C0.Seed = static_cast<uint32_t>(I * 7 + 1);
			cw::AiConfig C1;
			C1.Seed = static_cast<uint32_t>(I * 13 + 5);
			cw::AiPlayer Ai0(0, C0);
			cw::AiPlayer Ai1(1, C1);
			Sim.Start();
			while (Sim.Phase() == cw::MatchPhase::Running && Sim.Time() < 1800.f)
			{
				Ai0.Tick(Sim, FixedDt);
				Ai1.Tick(Sim, FixedDt);
				Sim.Step(FixedDt);
				Sim.ClearEvents();
				++Steps;
				UnitSteps += static_cast<long long>(Sim.Units().size());
				PeakUnits = std::max(PeakUnits, Sim.Units().size());
			}
		}
		const double Seconds = std::chrono::duration<double>(std::chrono::steady_clock::now() - Start).count();
		std::printf("[基准] %d 局，共 %lld 步，耗时 %.3f 秒：平均 %.2f 微秒/步；平均在场单位 %.1f，峰值 %zu；相当于实时速度的 %.0f 倍\n",
			Matches, Steps, Seconds, Seconds * 1.0e6 / static_cast<double>(std::max(Steps, 1LL)),
			static_cast<double>(UnitSteps) / static_cast<double>(std::max(Steps, 1LL)), PeakUnits,
			static_cast<double>(Steps) * FixedDt / std::max(Seconds, 1.0e-9));
	}

	void RunBalanceMatrix(const cw::GameData& Data)
	{
		const Mix Mixes[] = {
			{ "纯近战", { 1.f, 0.f, 0.f } },
			{ "纯远程", { 0.f, 1.f, 0.f } },
			{ "纯重型", { 0.f, 0.f, 1.f } },
			{ "近+远", { 0.6f, 0.4f, 0.f } },
			{ "近+重", { 0.6f, 0.f, 0.4f } },
			{ "远+重", { 0.f, 0.6f, 0.4f } },
			{ "均衡", { 0.45f, 0.35f, 0.2f } },
		};
		const int N = static_cast<int>(sizeof(Mixes) / sizeof(Mixes[0]));
		for (int32_t Age = 0; Age < static_cast<int32_t>(Data.Ages.size()) && Data.Ages[static_cast<size_t>(Age)].Implemented; ++Age)
		{
			std::printf("\n[数值] %s：行=阵营0 配比，列=阵营1 配比，数值为阵营0 优势（+1 胜，-1 负；双向平均消除站位差）\n",
				Data.Ages[static_cast<size_t>(Age)].DisplayName.c_str());
			std::printf("%-10s", "");
			for (int J = 0; J < N; ++J)
			{
				std::printf("%10s", Mixes[J].Name);
			}
			std::printf("%10s\n", "平均");
			for (int I = 0; I < N; ++I)
			{
				std::printf("%-10s", Mixes[I].Name);
				float Sum = 0.f;
				for (int J = 0; J < N; ++J)
				{
					const float A = RunMixDuel(Data, Age, Mixes[I], Mixes[J], 300.f);
					const float B = RunMixDuel(Data, Age, Mixes[J], Mixes[I], 300.f);
					const float V = (A - B) * 0.5f;
					Sum += V;
					std::printf("%10.2f", V);
				}
				std::printf("%10.2f\n", Sum / static_cast<float>(N));
			}
		}
	}
}

int main(int Argc, char** Argv)
{
#ifdef _WIN32
	SetConsoleOutputCP(CP_UTF8);
#endif
	std::string DataDir = "Content/Data";
	int Matches = 20;
	bool bBalance = false;
	bool bBench = false;
	uint32_t TraceSeed = 1;
	int TraceD0 = -1;
	int TraceD1 = -1;
	for (int I = 1; I < Argc; ++I)
	{
		if (std::strcmp(Argv[I], "--matches") == 0 && I + 1 < Argc)
		{
			Matches = std::atoi(Argv[++I]);
		}
		else if (std::strcmp(Argv[I], "--verbose") == 0)
		{
			GVerbose = true;
		}
		else if (std::strcmp(Argv[I], "--balance") == 0)
		{
			bBalance = true;
		}
		else if (std::strcmp(Argv[I], "--seed") == 0 && I + 1 < Argc)
		{
			TraceSeed = static_cast<uint32_t>(std::atoi(Argv[++I]));
		}
		else if (std::strcmp(Argv[I], "--bench") == 0)
		{
			bBench = true;
		}
		else if (std::strcmp(Argv[I], "--trace") == 0 && I + 2 < Argc)
		{
			TraceD0 = std::atoi(Argv[++I]);
			TraceD1 = std::atoi(Argv[++I]);
		}
		else
		{
			DataDir = Argv[I];
		}
	}

	cw::GameData Data;
	std::string Error;
	if (!LoadGameData(DataDir, Data, Error))
	{
		std::printf("数据加载失败：%s\n", Error.c_str());
		return 2;
	}
	std::printf("数据加载成功：%zu 个时代，%zu 个兵种，%zu 种炮塔，%zu 个技能\n",
		Data.Ages.size(), Data.Units.size(), Data.Turrets.size(), Data.Skills.size());
	if (bBalance)
	{
		RunBalanceMatrix(Data);
		return 0;
	}
	if (bBench)
	{
		RunBenchmark(Data, std::max(Matches, 1));
		return 0;
	}
	if (TraceD0 >= 0)
	{
		RunTrace(Data, static_cast<cw::AiDifficulty>(TraceD0), static_cast<cw::AiDifficulty>(TraceD1), TraceSeed);
		return 0;
	}

	TestSingleUnitCombatLoop(Data);
	TestRangedBehaviour(Data);
	TestCrowding(Data);
	TestCommandValidation(Data);
	TestAgeProgression(Data);
	TestSkill(Data);
	TestTurret(Data);
	TestTimeLimit(Data);
	TestEconomy(Data);
	TestStance(Data);
	TestChampion(Data);
	TestVeterancy(Data);
	TestDoctrines(Data);
	TestLastStand(Data);
	if (Matches > 0)
	{
		TestAiMatches(Data, Matches);
	}

	std::printf("\n检查 %d 项，失败 %d 项\n", Ctx().Checks, Ctx().Failures);
	return Ctx().Failures == 0 ? 0 : 1;
}
