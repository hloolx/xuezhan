// 测试工具：断言宏与每步不变量检查
#pragma once

#include "Sim/Simulation.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <string>
#include <vector>

namespace harness
{
	struct TestContext
	{
		int Checks = 0;
		int Failures = 0;
	};

	TestContext& Ctx();

#define CW_CHECK(Cond, Msg)                                                                         \
	do                                                                                              \
	{                                                                                               \
		++harness::Ctx().Checks;                                                                    \
		if (!(Cond))                                                                                \
		{                                                                                           \
			++harness::Ctx().Failures;                                                              \
			std::printf("  [失败] %s:%d  %s  -- %s\n", __FILE__, __LINE__, #Cond, std::string(Msg).c_str()); \
		}                                                                                           \
	} while (0)

	// 不变量统计：在完整对局中逐步检查
	struct InvariantReport
	{
		int Ticks = 0;
		int EnemyOverlap = 0;     // 敌我单位重叠/穿越
		int AllyOverlap = 0;      // 友军间距小于规则下限
		int OutOfLane = 0;        // 单位超出战场
		int DeadActing = 0;       // 死亡单位发起攻击
		int MeleeOutOfRange = 0;  // 隔空近战
		int NegativeGold = 0;
		int BadHp = 0;
		int MatchEndedEvents = 0;
		int HitAfterDeath = 0;    // 已死亡单位再次受击
		float WorstEnemyGap = 1.0e9f;
		std::vector<int32_t> DyingLastTick;

		int Total() const
		{
			return EnemyOverlap + AllyOverlap + OutOfLane + DeadActing + MeleeOutOfRange + NegativeGold + BadHp
				+ HitAfterDeath + (MatchEndedEvents > 1 ? 1 : 0);
		}
	};

	inline void CheckInvariants(const cw::Simulation& Sim, InvariantReport& Rep)
	{
		const cw::GameData& Data = Sim.Data();
		const float Tol = 0.05f;
		++Rep.Ticks;

		// 敌我不重叠、不穿越：阵营 0 最右单位必须在阵营 1 最左单位左侧且保持接触距离
		const cw::Unit* Front0 = nullptr;
		const cw::Unit* Front1 = nullptr;
		std::vector<const cw::Unit*> Alive[2][cw::MaxLaneRows];
		for (const cw::Unit& U : Sim.Units())
		{
			const cw::UnitDef& D = Data.Units[static_cast<size_t>(U.Def)];
			if (U.State == cw::UnitState::Dying)
			{
				continue;
			}
			if (U.Row < 0 || U.Row >= Data.Rules.LaneRows)
			{
				++Rep.OutOfLane;
				continue;
			}
			if (!U.Champion)
			{
				Alive[U.Team][U.Row].push_back(&U); // 统帅不参与友军间距
			}
			if (U.Team == 0 && (Front0 == nullptr || U.X > Front0->X))
			{
				Front0 = &U;
			}
			if (U.Team == 1 && (Front1 == nullptr || U.X < Front1->X))
			{
				Front1 = &U;
			}
			if (U.X < Sim.BaseFrontX(0) - D.Radius - 1.f || U.X > Sim.BaseFrontX(1) + D.Radius + 1.f)
			{
				++Rep.OutOfLane;
			}
			if (!(U.Hp > 0.f) || U.Hp > U.MaxHp + 0.01f || U.MaxHp <= 0.f)
			{
				++Rep.BadHp;
			}
		}
		if (Front0 != nullptr && Front1 != nullptr)
		{
			const float Gap = (Front1->X - Front0->X) - Data.Units[static_cast<size_t>(Front0->Def)].Radius
				- Data.Units[static_cast<size_t>(Front1->Def)].Radius;
			Rep.WorstEnemyGap = std::min(Rep.WorstEnemyGap, Gap);
			if (Gap < -Tol)
			{
				++Rep.EnemyOverlap;
			}
		}
		for (int T = 0; T < 2; ++T)
		{
			for (int Row = 0; Row < cw::MaxLaneRows; ++Row)
			{
				std::vector<const cw::Unit*>& L = Alive[T][Row];
				std::sort(L.begin(), L.end(), [](const cw::Unit* A, const cw::Unit* B) { return A->X < B->X; });
				for (size_t I = 1; I < L.size(); ++I)
				{
					const float Need = (Data.Units[static_cast<size_t>(L[I - 1]->Def)].Radius + Data.Units[static_cast<size_t>(L[I]->Def)].Radius)
						* Data.Rules.AllySpacingFactor;
					if (L[I]->X - L[I - 1]->X < Need - Tol)
					{
						++Rep.AllyOverlap;
					}
				}
			}
		}
		for (int T = 0; T < 2; ++T)
		{
			if (Sim.Team(T).Gold < -0.001)
			{
				++Rep.NegativeGold;
			}
			if (Sim.Team(T).BaseHp < 0.f)
			{
				++Rep.BadHp;
			}
		}

		// 事件检查
		auto WasDying = [&Rep](int32_t Id)
		{
			return std::find(Rep.DyingLastTick.begin(), Rep.DyingLastTick.end(), Id) != Rep.DyingLastTick.end();
		};
		for (const cw::SimEvent& Ev : Sim.Events())
		{
			if (Ev.Type == cw::EventType::MatchEnded)
			{
				++Rep.MatchEndedEvents;
			}
			if (Ev.Type == cw::EventType::UnitHit && WasDying(Ev.A))
			{
				++Rep.HitAfterDeath;
			}
			if (Ev.Type != cw::EventType::UnitAttackStart)
			{
				continue;
			}
			if (WasDying(Ev.A))
			{
				++Rep.DeadActing;
				continue;
			}
			const cw::Unit* U = Sim.FindUnit(Ev.A);
			if (U == nullptr)
			{
				continue; // 已被移除（不应发生在同一步内）
			}
			if (U->State == cw::UnitState::Dying)
			{
				// 同一步内先发起攻击、后被结算击杀是合法的（同时结算），只统计发起时已死亡的情况
				continue;
			}
			const cw::UnitDef& D = Data.Units[static_cast<size_t>(U->Def)];
			if (D.ProjectileSpeed <= 0.f && Ev.B >= 0)
			{
				const cw::Unit* Tgt = Sim.FindUnit(Ev.B);
				if (Tgt != nullptr)
				{
					const float Edge = std::fabs(Tgt->X - U->X) - D.Radius - Data.Units[static_cast<size_t>(Tgt->Def)].Radius;
					// 容差：同一步内目标可能后撤（驻守后撤、统帅接到坚守指令）最多“最快移速 × 国策移速上限 × 步长”
					// （服务器结算命中时会重新检查射程）
					float MaxSpeed = 0.f;
					for (const cw::UnitDef& UD : Data.Units)
					{
						MaxSpeed = std::max(MaxSpeed, UD.MoveSpeed);
					}
					const float RetreatSlack = MaxSpeed * 1.5f * 0.05f;
					if (Edge > Sim.UnitRange(*U) + 1.f + RetreatSlack)
					{
						++Rep.MeleeOutOfRange;
					}
				}
			}
		}

		Rep.DyingLastTick.clear();
		for (const cw::Unit& U : Sim.Units())
		{
			if (U.State == cw::UnitState::Dying)
			{
				Rep.DyingLastTick.push_back(U.Id);
			}
		}
	}
}
