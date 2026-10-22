#include "View/CWModels.h"

#include "Components/SceneComponent.h"
#include "Components/StaticMeshComponent.h"
#include "GameFramework/Actor.h"
#include "Materials/MaterialInstanceDynamic.h"

// 注意：UE 的 Unity Build 会把多个 .cpp 合并编译，using 指令只放在命名空间内部，避免泄漏到其他文件
namespace CWModelsDetail
{
	using namespace CWVisual;

	// 风格化配色（线性空间）
	const FLinearColor CSkin(0.80f, 0.55f, 0.40f);
	const FLinearColor CFur(0.36f, 0.22f, 0.12f);
	const FLinearColor CLeather(0.50f, 0.33f, 0.18f);
	const FLinearColor CLeatherDark(0.22f, 0.14f, 0.08f);
	const FLinearColor CWood(0.42f, 0.27f, 0.14f);
	const FLinearColor CStone(0.45f, 0.45f, 0.47f);
	const FLinearColor CSteel(0.62f, 0.64f, 0.68f);
	const FLinearColor CIron(0.20f, 0.20f, 0.22f);
	const FLinearColor COlive(0.27f, 0.30f, 0.15f);
	const FLinearColor COliveDark(0.17f, 0.19f, 0.10f);
	const FLinearColor CLinen(0.78f, 0.72f, 0.58f);
	const FLinearColor CPadded(0.60f, 0.50f, 0.35f);
	const FLinearColor CBrick(0.55f, 0.20f, 0.12f);
	const FLinearColor CThatch(0.72f, 0.58f, 0.28f);
	const FLinearColor CMud(0.45f, 0.33f, 0.22f);
	const FLinearColor CConcrete(0.55f, 0.55f, 0.52f);
	const FLinearColor CIvory(0.92f, 0.88f, 0.76f);
	const FLinearColor CHorse(0.40f, 0.25f, 0.14f);
	const FLinearColor CMammoth(0.38f, 0.26f, 0.17f);

	// 记录材质以便受击闪白
	struct FCWModelBuilder
	{
		AActor* Owner = nullptr;
		TArray<UMaterialInstanceDynamic*>* Mats = nullptr;
		TArray<FLinearColor>* Colors = nullptr;

		UStaticMeshComponent* Part(USceneComponent* Parent, EShape Shape, const FVector& Loc, const FVector& Size, const FMaterialParams& P,
			const FRotator& Rot = FRotator::ZeroRotator, bool bShadow = true)
		{
			UStaticMeshComponent* C = AddPart(Owner, Parent, Shape, Loc, Size, Rot, P, bShadow);
			if (Mats && Colors)
			{
				if (UMaterialInstanceDynamic* M = Cast<UMaterialInstanceDynamic>(C->GetMaterial(0)))
				{
					Mats->Add(M);
					Colors->Add(P.Color);
				}
			}
			return C;
		}

		USceneComponent* Pivot(USceneComponent* Parent, const FVector& Loc, const FRotator& Rot = FRotator::ZeroRotator)
		{
			return AddPivot(Owner, Parent, Loc, Rot);
		}
	};

	enum class EHelmet : uint8 { None, Band, Hood, Kettle, Great, Cap, Steel, Riot, Sleek, Horns, Crown, Officer };
	enum class EWeapon : uint8 { Axe, Sling, Sword, Crossbow, Lance, Spear, Shovel, Rifle, Baton, Launcher, EnergyBlade, LaserRifle, Club, Hammer };
	const FLinearColor CGold(1.0f, 0.72f, 0.22f);
	const FLinearColor CRiotBlack(0.05f, 0.05f, 0.06f);
	const FLinearColor CArmorWhite(0.82f, 0.84f, 0.88f);
	const FLinearColor CEnergyCyan(0.30f, 0.90f, 1.00f);
	const FLinearColor CGunmetal(0.28f, 0.29f, 0.31f);

	struct FHumanStyle
	{
		FLinearColor Skin = CSkin;
		FLinearColor Torso = CLinen;
		FLinearColor Legs = CLeather;
		FLinearColor Accent = FLinearColor::White;
		bool bMetalTorso = false;
		EHelmet Helmet = EHelmet::None;
		EWeapon Weapon = EWeapon::Axe;
		bool bShield = false;
		bool bRiotShield = false; // 长方形防暴盾
		bool bLegs = true;
		bool bBackpack = false;
	};

	// 人形：脚底位于原点，前方 +X
	void BuildHuman(FCWModelBuilder& B, USceneComponent* Parent, const FHumanStyle& S, FCWUnitRig& Rig, float Scale)
	{
		USceneComponent* HumanRoot = B.Pivot(Parent, FVector::ZeroVector);
		HumanRoot->SetRelativeScale3D(FVector(Scale));

		if (S.bLegs)
		{
			Rig.LegL = B.Pivot(HumanRoot, FVector(0.f, 10.f, 50.f));
			B.Part(Rig.LegL, EShape::Cylinder, FVector(0.f, 0.f, -24.f), FVector(15.f, 15.f, 48.f), Paint(S.Legs));
			B.Part(Rig.LegL, EShape::Cube, FVector(5.f, 0.f, -47.f), FVector(24.f, 14.f, 8.f), Paint(CLeatherDark));
			Rig.LegR = B.Pivot(HumanRoot, FVector(0.f, -10.f, 50.f));
			B.Part(Rig.LegR, EShape::Cylinder, FVector(0.f, 0.f, -24.f), FVector(15.f, 15.f, 48.f), Paint(S.Legs));
			B.Part(Rig.LegR, EShape::Cube, FVector(5.f, 0.f, -47.f), FVector(24.f, 14.f, 8.f), Paint(CLeatherDark));
		}
		else
		{
			// 骑乘：两条腿跨在坐骑两侧
			B.Part(HumanRoot, EShape::Cylinder, FVector(6.f, 18.f, 34.f), FVector(14.f, 14.f, 40.f), Paint(S.Legs), FRotator(25.f, 0.f, -20.f));
			B.Part(HumanRoot, EShape::Cylinder, FVector(6.f, -18.f, 34.f), FVector(14.f, 14.f, 40.f), Paint(S.Legs), FRotator(25.f, 0.f, 20.f));
		}

		Rig.Body = B.Pivot(HumanRoot, FVector(0.f, 0.f, 50.f));
		USceneComponent* Body = Rig.Body;
		B.Part(Body, EShape::Cube, FVector(0.f, 0.f, 5.f), FVector(26.f, 30.f, 14.f), Paint(S.Legs));
		B.Part(Body, EShape::Cube, FVector(0.f, 0.f, 31.f), FVector(26.f, 34.f, 40.f), S.bMetalTorso ? Metal(S.Torso) : Paint(S.Torso));
		B.Part(Body, EShape::Cube, FVector(0.f, 0.f, 13.f), FVector(28.f, 36.f, 6.f), Paint(S.Accent, 0.6f));
		B.Part(Body, EShape::Cube, FVector(14.f, 0.f, 34.f), FVector(3.f, 20.f, 16.f), Paint(S.Accent, 0.6f));
		B.Part(Body, EShape::Sphere, FVector(0.f, 0.f, 64.f), FVector(26.f, 26.f, 28.f), Paint(S.Skin, 0.6f));
		// 眼睛：帮助在远处辨认朝向
		B.Part(Body, EShape::Sphere, FVector(12.f, 5.f, 67.f), FVector(4.f, 4.f, 5.f), Paint(FLinearColor(0.02f, 0.02f, 0.02f), 0.3f), FRotator::ZeroRotator, false);
		B.Part(Body, EShape::Sphere, FVector(12.f, -5.f, 67.f), FVector(4.f, 4.f, 5.f), Paint(FLinearColor(0.02f, 0.02f, 0.02f), 0.3f), FRotator::ZeroRotator, false);

		switch (S.Helmet)
		{
		case EHelmet::Band:
			B.Part(Body, EShape::Cylinder, FVector(0.f, 0.f, 68.f), FVector(28.f, 28.f, 5.f), Paint(S.Accent));
			B.Part(Body, EShape::Sphere, FVector(-3.f, 0.f, 73.f), FVector(27.f, 27.f, 18.f), Paint(CFur, 0.9f));
			break;
		case EHelmet::Hood:
			B.Part(Body, EShape::Sphere, FVector(-3.f, 0.f, 69.f), FVector(30.f, 30.f, 27.f), Paint(S.Torso, 0.9f));
			B.Part(Body, EShape::Cylinder, FVector(0.f, 0.f, 62.f), FVector(31.f, 31.f, 4.f), Paint(S.Accent));
			break;
		case EHelmet::Kettle:
			B.Part(Body, EShape::Cylinder, FVector(0.f, 0.f, 74.f), FVector(40.f, 40.f, 3.f), Metal(CSteel));
			B.Part(Body, EShape::Sphere, FVector(0.f, 0.f, 75.f), FVector(27.f, 27.f, 20.f), Metal(CSteel));
			break;
		case EHelmet::Great:
			B.Part(Body, EShape::Cylinder, FVector(0.f, 0.f, 66.f), FVector(30.f, 30.f, 32.f), Metal(CSteel));
			B.Part(Body, EShape::Cube, FVector(15.f, 0.f, 68.f), FVector(2.f, 18.f, 3.f), Paint(CIron), FRotator::ZeroRotator, false);
			B.Part(Body, EShape::Cone, FVector(-2.f, 0.f, 92.f), FVector(10.f, 10.f, 24.f), Paint(S.Accent));
			break;
		case EHelmet::Cap:
			B.Part(Body, EShape::Sphere, FVector(0.f, 0.f, 72.f), FVector(28.f, 28.f, 16.f), Paint(S.Torso));
			B.Part(Body, EShape::Cube, FVector(13.f, 0.f, 69.f), FVector(12.f, 22.f, 3.f), Paint(S.Torso));
			break;
		case EHelmet::Steel:
			B.Part(Body, EShape::Sphere, FVector(0.f, 0.f, 72.f), FVector(32.f, 32.f, 20.f), Metal(COlive * 0.9f, 0.5f));
			B.Part(Body, EShape::Cylinder, FVector(0.f, 0.f, 67.f), FVector(37.f, 37.f, 3.f), Metal(COlive * 0.9f, 0.5f));
			break;
		case EHelmet::Riot:
			B.Part(Body, EShape::Sphere, FVector(0.f, 0.f, 71.f), FVector(32.f, 32.f, 27.f), Paint(CRiotBlack, 0.35f));
			B.Part(Body, EShape::Cube, FVector(13.f, 0.f, 66.f), FVector(4.f, 27.f, 13.f), Paint(FLinearColor(0.20f, 0.30f, 0.36f), 0.08f), FRotator::ZeroRotator, false);
			break;
		case EHelmet::Sleek:
		{
			B.Part(Body, EShape::Sphere, FVector(0.f, 0.f, 68.f), FVector(31.f, 30.f, 33.f), Metal(CArmorWhite, 0.3f));
			FMaterialParams Visor = Paint(S.Accent, 0.2f);
			Visor.Emissive = 8.f;
			B.Part(Body, EShape::Cube, FVector(14.f, 0.f, 67.f), FVector(4.f, 24.f, 7.f), Visor, FRotator::ZeroRotator, false);
			break;
		}
		case EHelmet::Horns:
			// 兽骨头冠：皮毛头箍 + 一对弯角
			B.Part(Body, EShape::Sphere, FVector(-3.f, 0.f, 73.f), FVector(29.f, 29.f, 18.f), Paint(CFur, 0.9f));
			B.Part(Body, EShape::Cone, FVector(-2.f, 14.f, 86.f), FVector(9.f, 9.f, 28.f), Paint(CIvory, 0.4f), FRotator(0.f, 0.f, -35.f));
			B.Part(Body, EShape::Cone, FVector(-2.f, -14.f, 86.f), FVector(9.f, 9.f, 28.f), Paint(CIvory, 0.4f), FRotator(0.f, 0.f, 35.f));
			break;
		case EHelmet::Crown:
		{
			// 金冠：冠圈 + 一圈尖齿 + 宝石
			B.Part(Body, EShape::Cylinder, FVector(0.f, 0.f, 77.f), FVector(30.f, 30.f, 8.f), Metal(CGold, 0.25f));
			for (int32 I = 0; I < 6; ++I)
			{
				const float A = I * PI / 3.f;
				B.Part(Body, EShape::Cone, FVector(FMath::Cos(A) * 13.f, FMath::Sin(A) * 13.f, 86.f), FVector(6.f, 6.f, 11.f), Metal(CGold, 0.25f));
			}
			FMaterialParams Gem = Paint(S.Accent, 0.2f);
			Gem.Emissive = 3.f;
			B.Part(Body, EShape::Sphere, FVector(14.f, 0.f, 78.f), FVector(6.f), Gem, FRotator::ZeroRotator, false);
			break;
		}
		case EHelmet::Officer:
			// 军官大檐帽：深色帽身 + 金色帽带 + 帽檐
			B.Part(Body, EShape::Cylinder, FVector(0.f, 0.f, 76.f), FVector(32.f, 32.f, 12.f), Paint(FLinearColor(0.08f, 0.08f, 0.1f), 0.6f));
			B.Part(Body, EShape::Cylinder, FVector(0.f, 0.f, 71.f), FVector(29.f, 29.f, 4.f), Metal(CGold, 0.3f));
			B.Part(Body, EShape::Cube, FVector(14.f, 0.f, 70.f), FVector(14.f, 24.f, 2.f), Paint(FLinearColor(0.05f, 0.05f, 0.06f), 0.4f));
			break;
		default:
			break;
		}

		// 武器手（ArmR）放在 +Y 侧：双方镜头都从单位的这一侧观察，武器动作不会被身体挡住
		Rig.ArmL = B.Pivot(Body, FVector(0.f, -22.f, 46.f));
		B.Part(Rig.ArmL, EShape::Cylinder, FVector(0.f, 0.f, -17.f), FVector(11.f, 11.f, 34.f), S.bMetalTorso ? Metal(S.Torso) : Paint(S.Torso));
		B.Part(Rig.ArmL, EShape::Sphere, FVector(0.f, 0.f, -36.f), FVector(11.f, 11.f, 11.f), Paint(S.Skin));
		Rig.ArmR = B.Pivot(Body, FVector(0.f, 22.f, 46.f));
		B.Part(Rig.ArmR, EShape::Cylinder, FVector(0.f, 0.f, -17.f), FVector(11.f, 11.f, 34.f), S.bMetalTorso ? Metal(S.Torso) : Paint(S.Torso));
		B.Part(Rig.ArmR, EShape::Sphere, FVector(0.f, 0.f, -36.f), FVector(11.f, 11.f, 11.f), Paint(S.Skin));
		USceneComponent* HandR = B.Pivot(Rig.ArmR, FVector(0.f, 0.f, -37.f));
		USceneComponent* HandL = B.Pivot(Rig.ArmL, FVector(0.f, 0.f, -37.f));

		// 武器沿手部 -Z 方向延伸：手臂抬起（俯仰角为正）时武器随之挥动
		switch (S.Weapon)
		{
		case EWeapon::Axe:
			B.Part(HandR, EShape::Cylinder, FVector(0.f, 0.f, -24.f), FVector(5.f, 5.f, 56.f), Paint(CWood));
			B.Part(HandR, EShape::Cube, FVector(7.f, 0.f, -47.f), FVector(14.f, 7.f, 16.f), Paint(CStone, 0.9f));
			Rig.Style = ECWAttackStyle::Chop;
			Rig.ArmRestPitch = 20.f;
			Rig.Muzzle = HandR;
			break;
		case EWeapon::Sling:
			B.Part(HandR, EShape::Cylinder, FVector(0.f, 0.f, -20.f), FVector(2.f, 2.f, 40.f), Paint(CLeather));
			B.Part(HandR, EShape::Sphere, FVector(0.f, 0.f, -41.f), FVector(9.f, 9.f, 9.f), Paint(CStone));
			Rig.Style = ECWAttackStyle::Throw;
			Rig.ArmRestPitch = 10.f;
			Rig.Muzzle = B.Pivot(HandR, FVector(0.f, 0.f, -41.f));
			break;
		case EWeapon::Sword:
			B.Part(HandR, EShape::Cube, FVector(0.f, 0.f, -36.f), FVector(3.f, 7.f, 60.f), Metal(CSteel, 0.25f));
			B.Part(HandR, EShape::Cube, FVector(0.f, 0.f, -5.f), FVector(6.f, 18.f, 3.f), Metal(CIron));
			Rig.Style = ECWAttackStyle::Chop;
			Rig.ArmRestPitch = 25.f;
			Rig.Muzzle = HandR;
			break;
		case EWeapon::Crossbow:
			B.Part(HandR, EShape::Cube, FVector(0.f, 0.f, -18.f), FVector(8.f, 6.f, 46.f), Paint(CWood));
			B.Part(HandR, EShape::Cube, FVector(0.f, 0.f, -38.f), FVector(5.f, 48.f, 4.f), Paint(CWood * 0.8f));
			Rig.Style = ECWAttackStyle::Shoot;
			Rig.ArmRestPitch = 88.f;
			Rig.Muzzle = B.Pivot(HandR, FVector(0.f, 0.f, -44.f));
			break;
		case EWeapon::Lance:
			B.Part(HandR, EShape::Cylinder, FVector(0.f, 0.f, -80.f), FVector(7.f, 7.f, 190.f), Paint(S.Accent * 0.8f));
			B.Part(HandR, EShape::Cone, FVector(0.f, 0.f, -186.f), FVector(9.f, 9.f, 24.f), Metal(CSteel), FRotator(180.f, 0.f, 0.f));
			Rig.Style = ECWAttackStyle::Thrust;
			Rig.ArmRestPitch = 80.f;
			Rig.Muzzle = B.Pivot(HandR, FVector(0.f, 0.f, -190.f));
			break;
		case EWeapon::Spear:
			B.Part(HandR, EShape::Cylinder, FVector(0.f, 0.f, -50.f), FVector(5.f, 5.f, 130.f), Paint(CWood));
			B.Part(HandR, EShape::Cone, FVector(0.f, 0.f, -120.f), FVector(8.f, 8.f, 20.f), Paint(CStone), FRotator(180.f, 0.f, 0.f));
			Rig.Style = ECWAttackStyle::Thrust;
			Rig.ArmRestPitch = 70.f;
			Rig.Muzzle = B.Pivot(HandR, FVector(0.f, 0.f, -125.f));
			break;
		case EWeapon::Shovel:
			B.Part(HandR, EShape::Cylinder, FVector(0.f, 0.f, -25.f), FVector(5.f, 5.f, 60.f), Paint(CWood));
			B.Part(HandR, EShape::Cube, FVector(0.f, 0.f, -58.f), FVector(3.f, 17.f, 20.f), Metal(CIron, 0.5f));
			Rig.Style = ECWAttackStyle::Chop;
			Rig.ArmRestPitch = 20.f;
			Rig.Muzzle = HandR;
			break;
		case EWeapon::Rifle:
			B.Part(HandR, EShape::Cube, FVector(0.f, 0.f, -24.f), FVector(7.f, 5.f, 70.f), Paint(CWood));
			B.Part(HandR, EShape::Cylinder, FVector(0.f, 0.f, -70.f), FVector(3.f, 3.f, 32.f), Metal(CIron));
			Rig.Style = ECWAttackStyle::Shoot;
			Rig.ArmRestPitch = 90.f;
			Rig.Muzzle = B.Pivot(HandR, FVector(0.f, 0.f, -88.f));
			break;
		case EWeapon::Baton:
			B.Part(HandR, EShape::Cylinder, FVector(0.f, 0.f, -22.f), FVector(5.f, 5.f, 48.f), Paint(CRiotBlack, 0.4f));
			Rig.Style = ECWAttackStyle::Chop;
			Rig.ArmRestPitch = 25.f;
			Rig.Muzzle = HandR;
			break;
		case EWeapon::Launcher:
			B.Part(HandR, EShape::Cylinder, FVector(0.f, 0.f, -30.f), FVector(13.f, 13.f, 96.f), Metal(COliveDark, 0.6f));
			B.Part(HandR, EShape::Cylinder, FVector(0.f, 0.f, -79.f), FVector(16.f, 16.f, 8.f), Metal(CIron));
			B.Part(HandR, EShape::Cube, FVector(-7.f, 0.f, -18.f), FVector(6.f, 8.f, 14.f), Metal(CIron));
			Rig.Style = ECWAttackStyle::Shoot;
			Rig.ArmRestPitch = 92.f;
			Rig.Muzzle = B.Pivot(HandR, FVector(0.f, 0.f, -84.f));
			break;
		case EWeapon::EnergyBlade:
		{
			B.Part(HandR, EShape::Cylinder, FVector(0.f, 0.f, -5.f), FVector(6.f, 6.f, 14.f), Metal(CGunmetal));
			FMaterialParams Blade = Paint(CEnergyCyan, 0.2f);
			Blade.Emissive = 12.f;
			B.Part(HandR, EShape::Cube, FVector(0.f, 0.f, -46.f), FVector(3.f, 7.f, 72.f), Blade, FRotator::ZeroRotator, false);
			Rig.Style = ECWAttackStyle::Chop;
			Rig.ArmRestPitch = 25.f;
			Rig.Muzzle = HandR;
			break;
		}
		case EWeapon::Club:
			// 巨骨棒：粗柄 + 末端骨球
			B.Part(HandR, EShape::Cylinder, FVector(0.f, 0.f, -28.f), FVector(8.f, 8.f, 64.f), Paint(CWood * 0.9f));
			B.Part(HandR, EShape::Sphere, FVector(0.f, 0.f, -62.f), FVector(22.f, 22.f, 26.f), Paint(CIvory, 0.5f));
			Rig.Style = ECWAttackStyle::Chop;
			Rig.ArmRestPitch = 25.f;
			Rig.Muzzle = HandR;
			break;
		case EWeapon::Hammer:
			// 动力重锤：金属长柄 + 方形锤头（侧面发光条）
		{
			B.Part(HandR, EShape::Cylinder, FVector(0.f, 0.f, -30.f), FVector(6.f, 6.f, 70.f), Metal(CGunmetal));
			B.Part(HandR, EShape::Cube, FVector(0.f, 0.f, -66.f), FVector(22.f, 36.f, 22.f), Metal(CIron, 0.35f));
			FMaterialParams Strip = Paint(S.Accent, 0.2f);
			Strip.Emissive = 6.f;
			B.Part(HandR, EShape::Cube, FVector(0.f, 0.f, -66.f), FVector(23.f, 8.f, 23.f), Strip, FRotator::ZeroRotator, false);
			Rig.Style = ECWAttackStyle::Chop;
			Rig.ArmRestPitch = 25.f;
			Rig.Muzzle = HandR;
			break;
		}
		case EWeapon::LaserRifle:
		{
			B.Part(HandR, EShape::Cube, FVector(0.f, 0.f, -22.f), FVector(8.f, 6.f, 64.f), Metal(CArmorWhite, 0.3f));
			FMaterialParams Glow = Paint(CEnergyCyan, 0.2f);
			Glow.Emissive = 10.f;
			B.Part(HandR, EShape::Cylinder, FVector(0.f, 0.f, -62.f), FVector(4.f, 4.f, 30.f), Glow, FRotator::ZeroRotator, false);
			Rig.Style = ECWAttackStyle::Shoot;
			Rig.ArmRestPitch = 90.f;
			Rig.Muzzle = B.Pivot(HandR, FVector(0.f, 0.f, -78.f));
			break;
		}
		default:
			break;
		}

		if (S.bShield)
		{
			B.Part(HandL, EShape::Cylinder, FVector(10.f, -6.f, -6.f), FVector(52.f, 52.f, 6.f), Paint(S.Accent, 0.55f), FRotator(90.f, 0.f, 0.f));
			B.Part(HandL, EShape::Sphere, FVector(14.f, -6.f, -6.f), FVector(12.f, 12.f, 12.f), Metal(CSteel));
		}
		if (S.bRiotShield)
		{
			B.Part(HandL, EShape::Cube, FVector(12.f, -8.f, -8.f), FVector(6.f, 58.f, 82.f), Paint(FLinearColor(0.18f, 0.25f, 0.30f), 0.08f));
			B.Part(HandL, EShape::Cube, FVector(15.f, -8.f, 22.f), FVector(4.f, 58.f, 7.f), Paint(S.Accent, 0.5f));
		}
		if (S.bBackpack)
		{
			B.Part(Body, EShape::Cube, FVector(-18.f, 0.f, 30.f), FVector(12.f, 26.f, 30.f), Paint(CLeather));
			for (int32 I = 0; I < 3; ++I)
			{
				B.Part(Body, EShape::Cylinder, FVector(-26.f, -8.f + 8.f * I, 30.f), FVector(6.f, 6.f, 26.f), Paint(FLinearColor(0.7f, 0.08f, 0.05f)));
			}
		}
		Rig.Height = 150.f * Scale;
		Rig.StrideLength = 55.f * Scale;
	}

	struct FBeastStyle
	{
		FLinearColor Body = CHorse;
		FLinearColor Accent = FLinearColor::White;
		float Length = 150.f;
		float Width = 55.f;
		float Height = 70.f;
		float LegLen = 85.f;
		float LegThick = 14.f;
		bool bMammoth = false;
		bool bCaparison = false;
	};

	// 四足坐骑：返回骑手座位枢轴
	USceneComponent* BuildQuadruped(FCWModelBuilder& B, USceneComponent* Parent, const FBeastStyle& S, FCWUnitRig& Rig)
	{
		USceneComponent* MountBody = B.Pivot(Parent, FVector(0.f, 0.f, S.LegLen));
		B.Part(MountBody, EShape::Sphere, FVector(0.f, 0.f, S.Height * 0.45f), FVector(S.Length, S.Width, S.Height), Paint(S.Body, 0.85f));

		const FVector LegOffsets[4] = {
			FVector(S.Length * 0.30f, S.Width * 0.30f, S.LegLen),
			FVector(S.Length * 0.30f, -S.Width * 0.30f, S.LegLen),
			FVector(-S.Length * 0.30f, S.Width * 0.30f, S.LegLen),
			FVector(-S.Length * 0.30f, -S.Width * 0.30f, S.LegLen),
		};
		for (const FVector& Offset : LegOffsets)
		{
			USceneComponent* Leg = B.Pivot(Parent, Offset);
			B.Part(Leg, EShape::Cylinder, FVector(0.f, 0.f, -S.LegLen * 0.5f), FVector(S.LegThick, S.LegThick, S.LegLen), Paint(S.Body * 0.85f, 0.85f));
			B.Part(Leg, EShape::Cylinder, FVector(0.f, 0.f, -S.LegLen + 5.f), FVector(S.LegThick * 1.2f, S.LegThick * 1.2f, 10.f), Paint(CLeatherDark));
			Rig.MountLegs.Add(Leg);
		}

		if (S.bMammoth)
		{
			B.Part(MountBody, EShape::Sphere, FVector(S.Length * 0.48f, 0.f, S.Height * 0.62f), FVector(S.Length * 0.42f, S.Width * 0.62f, S.Height * 0.72f), Paint(S.Body, 0.85f));
			B.Part(MountBody, EShape::Sphere, FVector(S.Length * 0.42f, S.Width * 0.33f, S.Height * 0.70f), FVector(10.f, 34.f, 40.f), Paint(S.Body * 0.8f));
			B.Part(MountBody, EShape::Sphere, FVector(S.Length * 0.42f, -S.Width * 0.33f, S.Height * 0.70f), FVector(10.f, 34.f, 40.f), Paint(S.Body * 0.8f));
			B.Part(MountBody, EShape::Cone, FVector(S.Length * 0.70f, S.Width * 0.15f, S.Height * 0.30f), FVector(11.f, 11.f, 70.f), Paint(CIvory, 0.4f), FRotator(-115.f, 0.f, 0.f));
			B.Part(MountBody, EShape::Cone, FVector(S.Length * 0.70f, -S.Width * 0.15f, S.Height * 0.30f), FVector(11.f, 11.f, 70.f), Paint(CIvory, 0.4f), FRotator(-115.f, 0.f, 0.f));
			B.Part(MountBody, EShape::Cylinder, FVector(S.Length * 0.74f, 0.f, S.Height * 0.10f), FVector(15.f, 15.f, 75.f), Paint(S.Body, 0.85f), FRotator(12.f, 0.f, 0.f));
			// 毛发与战斗装饰
			B.Part(MountBody, EShape::Cube, FVector(-S.Length * 0.05f, 0.f, S.Height * 0.88f), FVector(S.Length * 0.45f, S.Width * 0.7f, 12.f), Paint(S.Accent, 0.7f));
		}
		else
		{
			B.Part(MountBody, EShape::Cylinder, FVector(S.Length * 0.46f, 0.f, S.Height * 0.85f), FVector(S.Width * 0.42f, S.Width * 0.42f, S.Height * 0.95f), Paint(S.Body, 0.85f), FRotator(-35.f, 0.f, 0.f));
			B.Part(MountBody, EShape::Cube, FVector(S.Length * 0.66f, 0.f, S.Height * 1.22f), FVector(S.Length * 0.32f, S.Width * 0.30f, S.Height * 0.32f), Paint(S.Body, 0.85f), FRotator(-25.f, 0.f, 0.f));
			B.Part(MountBody, EShape::Cube, FVector(S.Length * 0.40f, 0.f, S.Height * 1.05f), FVector(S.Length * 0.32f, 6.f, S.Height * 0.25f), Paint(CLeatherDark), FRotator(-35.f, 0.f, 0.f));
			B.Part(MountBody, EShape::Cylinder, FVector(-S.Length * 0.52f, 0.f, S.Height * 0.40f), FVector(10.f, 10.f, 50.f), Paint(CLeatherDark), FRotator(-35.f, 0.f, 0.f));
		}
		if (S.bCaparison)
		{
			B.Part(MountBody, EShape::Cube, FVector(0.f, 0.f, S.Height * 0.30f), FVector(S.Length * 0.85f, S.Width * 1.08f, S.Height * 0.55f), Paint(S.Accent, 0.8f));
			B.Part(MountBody, EShape::Cube, FVector(0.f, 0.f, S.Height * 0.02f), FVector(S.Length * 0.86f, S.Width * 1.09f, 6.f), Paint(CLinen, 0.8f));
		}
		Rig.Body = MountBody;
		Rig.bQuadruped = true;
		Rig.StrideLength = S.Length * 0.7f;
		return B.Pivot(MountBody, FVector(-S.Length * 0.05f, 0.f, S.Height * 0.80f));
	}

	// 统帅：体型更大的人形 + 披风 + 时代头饰/武器；未来统帅头顶有光环
	void BuildChampion(FCWModelBuilder& B, USceneComponent* Parent, int32 Team, const FString& Key, FCWUnitRig& Rig)
	{
		FHumanStyle S;
		S.Accent = TeamColor(Team);
		FLinearColor Cape = TeamColor(Team) * 0.8f;
		bool bHalo = false;
		if (Key == TEXT("Champion_Stone"))
		{
			S.Torso = CFur * 0.9f;
			S.Legs = CLeather;
			S.Helmet = EHelmet::Horns;
			S.Weapon = EWeapon::Club;
			Cape = CFur * 1.1f;
		}
		else if (Key == TEXT("Champion_Medieval"))
		{
			S.Torso = CGold * 0.8f;
			S.bMetalTorso = true;
			S.Legs = CSteel * 0.8f;
			S.Helmet = EHelmet::Crown;
			S.Weapon = EWeapon::Sword;
			S.bShield = true;
		}
		else if (Key == TEXT("Champion_Industrial"))
		{
			S.Torso = FLinearColor(0.16f, 0.2f, 0.26f);
			S.Legs = FLinearColor(0.1f, 0.11f, 0.14f);
			S.Helmet = EHelmet::Officer;
			S.Weapon = EWeapon::Sword;
			Cape = FLinearColor(0.12f, 0.14f, 0.18f);
		}
		else if (Key == TEXT("Champion_Modern"))
		{
			S.Torso = CGunmetal * 1.2f;
			S.bMetalTorso = true;
			S.Legs = CGunmetal;
			S.Helmet = EHelmet::Riot;
			S.Weapon = EWeapon::Hammer;
		}
		else
		{
			S.Torso = CArmorWhite;
			S.bMetalTorso = true;
			S.Legs = CGunmetal;
			S.Helmet = EHelmet::Sleek;
			S.Weapon = EWeapon::EnergyBlade;
			bHalo = true;
		}
		const float Scale = 1.32f;
		BuildHuman(B, Parent, S, Rig, Scale);
		USceneComponent* Body = Rig.Body;
		// 披风：从肩部垂到小腿，略微后倾
		B.Part(Body, EShape::Cube, FVector(-17.f, 0.f, 18.f), FVector(5.f, 40.f, 72.f), Paint(Cape, 0.85f), FRotator(-8.f, 0.f, 0.f));
		// 胸前徽记与肩甲
		B.Part(Body, EShape::Sphere, FVector(15.f, 0.f, 40.f), FVector(9.f, 12.f, 12.f), Metal(CGold, 0.3f));
		B.Part(Body, EShape::Sphere, FVector(0.f, 21.f, 50.f), FVector(18.f, 16.f, 12.f), Metal(S.bMetalTorso ? S.Torso : S.Accent * 0.7f, 0.4f));
		B.Part(Body, EShape::Sphere, FVector(0.f, -21.f, 50.f), FVector(18.f, 16.f, 12.f), Metal(S.bMetalTorso ? S.Torso : S.Accent * 0.7f, 0.4f));
		if (bHalo)
		{
			FMaterialParams Halo = Paint(CEnergyCyan, 0.2f);
			Halo.Emissive = 10.f;
			B.Part(Body, EShape::Cylinder, FVector(-4.f, 0.f, 100.f), FVector(34.f, 34.f, 2.f), Halo, FRotator(10.f, 0.f, 0.f), false);
		}
		Rig.Height = 150.f * Scale;
		Rig.StrideLength = 55.f * Scale;
	}

	void BuildArmoredCar(FCWModelBuilder& B, USceneComponent* Parent, int32 Team, FCWUnitRig& Rig)
	{
		USceneComponent* Hull = B.Pivot(Parent, FVector(0.f, 0.f, 0.f));
		B.Part(Hull, EShape::Cube, FVector(0.f, 0.f, 72.f), FVector(220.f, 120.f, 58.f), Metal(COlive, 0.6f));
		B.Part(Hull, EShape::Cube, FVector(88.f, 0.f, 62.f), FVector(50.f, 116.f, 34.f), Metal(COliveDark, 0.6f), FRotator(-20.f, 0.f, 0.f));
		B.Part(Hull, EShape::Cube, FVector(-20.f, 0.f, 124.f), FVector(110.f, 106.f, 46.f), Metal(COlive, 0.6f));
		B.Part(Hull, EShape::Cube, FVector(36.f, 0.f, 128.f), FVector(4.f, 80.f, 10.f), Paint(FLinearColor(0.05f, 0.05f, 0.05f), 0.2f), FRotator::ZeroRotator, false);
		B.Part(Hull, EShape::Cube, FVector(0.f, 0.f, 88.f), FVector(222.f, 122.f, 10.f), Paint(TeamColor(Team), 0.5f));
		B.Part(Hull, EShape::Cube, FVector(-60.f, 0.f, 150.f), FVector(30.f, 60.f, 6.f), Paint(TeamColor(Team), 0.5f));
		// 车轮：轴线沿 Y
		const FVector WheelPos[4] = {
			FVector(70.f, 64.f, 32.f), FVector(70.f, -64.f, 32.f), FVector(-70.f, 64.f, 32.f), FVector(-70.f, -64.f, 32.f),
		};
		for (const FVector& P : WheelPos)
		{
			USceneComponent* Wheel = B.Pivot(Parent, P);
			B.Part(Wheel, EShape::Cylinder, FVector::ZeroVector, FVector(64.f, 64.f, 24.f), Paint(FLinearColor(0.04f, 0.04f, 0.04f), 0.9f), FRotator(0.f, 0.f, 90.f));
			B.Part(Wheel, EShape::Cylinder, FVector::ZeroVector, FVector(30.f, 30.f, 26.f), Metal(CIron), FRotator(0.f, 0.f, 90.f));
			Rig.Wheels.Add(Wheel);
		}
		// 机枪塔
		Rig.Turret = B.Pivot(Hull, FVector(14.f, 0.f, 156.f));
		B.Part(Rig.Turret, EShape::Cylinder, FVector::ZeroVector, FVector(62.f, 62.f, 22.f), Metal(COliveDark, 0.6f));
		B.Part(Rig.Turret, EShape::Cube, FVector(26.f, 0.f, 10.f), FVector(10.f, 34.f, 26.f), Metal(COlive, 0.6f));
		B.Part(Rig.Turret, EShape::Cylinder, FVector(58.f, 0.f, 10.f), FVector(6.f, 6.f, 70.f), Metal(CIron), FRotator(-90.f, 0.f, 0.f));
		Rig.Muzzle = B.Pivot(Rig.Turret, FVector(94.f, 0.f, 10.f));
		Rig.Body = Hull;
		Rig.bVehicle = true;
		Rig.Style = ECWAttackStyle::Burst;
		Rig.TurretRest = Rig.Turret->GetRelativeLocation();
		Rig.Height = 200.f;
		Rig.StrideLength = 200.f;
	}

	// 主战坦克：履带底盘、倾斜装甲、长身管主炮
	void BuildTank(FCWModelBuilder& B, USceneComponent* Parent, int32 Team, FCWUnitRig& Rig)
	{
		USceneComponent* Hull = B.Pivot(Parent, FVector::ZeroVector);
		for (int32 Side = -1; Side <= 1; Side += 2)
		{
			B.Part(Hull, EShape::Cube, FVector(0.f, Side * 68.f, 34.f), FVector(260.f, 34.f, 52.f), Paint(FLinearColor(0.04f, 0.04f, 0.04f), 0.95f));
			for (int32 I = 0; I < 5; ++I)
			{
				USceneComponent* Wheel = B.Pivot(Parent, FVector(-96.f + I * 48.f, Side * 70.f, 26.f));
				B.Part(Wheel, EShape::Cylinder, FVector::ZeroVector, FVector(38.f, 38.f, 38.f), Metal(CGunmetal, 0.6f), FRotator(0.f, 0.f, 90.f));
				Rig.Wheels.Add(Wheel);
			}
		}
		B.Part(Hull, EShape::Cube, FVector(0.f, 0.f, 74.f), FVector(240.f, 112.f, 42.f), Metal(COlive, 0.55f));
		B.Part(Hull, EShape::Cube, FVector(104.f, 0.f, 64.f), FVector(50.f, 110.f, 30.f), Metal(COliveDark, 0.55f), FRotator(16.f, 0.f, 0.f));
		B.Part(Hull, EShape::Cube, FVector(0.f, 0.f, 96.f), FVector(242.f, 114.f, 6.f), Paint(TeamColor(Team), 0.5f));
		Rig.Turret = B.Pivot(Hull, FVector(-12.f, 0.f, 112.f));
		B.Part(Rig.Turret, EShape::Cube, FVector::ZeroVector, FVector(112.f, 92.f, 36.f), Metal(COlive, 0.55f));
		B.Part(Rig.Turret, EShape::Cube, FVector(46.f, 0.f, -2.f), FVector(30.f, 88.f, 28.f), Metal(COliveDark, 0.55f), FRotator(22.f, 0.f, 0.f));
		B.Part(Rig.Turret, EShape::Cylinder, FVector(112.f, 0.f, 4.f), FVector(13.f, 13.f, 150.f), Metal(CIron), FRotator(-90.f, 0.f, 0.f));
		B.Part(Rig.Turret, EShape::Cylinder, FVector(182.f, 0.f, 4.f), FVector(18.f, 18.f, 16.f), Metal(CIron), FRotator(-90.f, 0.f, 0.f));
		B.Part(Rig.Turret, EShape::Cylinder, FVector(-22.f, 26.f, 22.f), FVector(22.f, 22.f, 12.f), Metal(COliveDark, 0.55f));
		Rig.Muzzle = B.Pivot(Rig.Turret, FVector(194.f, 0.f, 4.f));
		Rig.TurretRest = Rig.Turret->GetRelativeLocation();
		Rig.Body = Hull;
		Rig.bVehicle = true;
		Rig.Style = ECWAttackStyle::Cannon;
		Rig.Height = 175.f;
		Rig.StrideLength = 220.f;
	}

	// 战斗机甲：双足、驾驶舱发光、双臂等离子炮、背部导弹舱
	void BuildMech(FCWModelBuilder& B, USceneComponent* Parent, int32 Team, FCWUnitRig& Rig)
	{
		const float HipZ = 150.f;
		const FLinearColor Frame = CArmorWhite * 0.85f;
		for (int32 Side = -1; Side <= 1; Side += 2)
		{
			USceneComponent* Leg = B.Pivot(Parent, FVector(0.f, Side * 42.f, HipZ));
			B.Part(Leg, EShape::Cylinder, FVector(0.f, 0.f, -40.f), FVector(36.f, 36.f, 82.f), Metal(CGunmetal, 0.5f));
			B.Part(Leg, EShape::Cube, FVector(8.f, 0.f, -84.f), FVector(40.f, 40.f, 26.f), Metal(Frame, 0.4f));
			B.Part(Leg, EShape::Cylinder, FVector(8.f, 0.f, -114.f), FVector(28.f, 28.f, 60.f), Metal(CGunmetal, 0.5f));
			B.Part(Leg, EShape::Cube, FVector(16.f, 0.f, -144.f), FVector(64.f, 42.f, 14.f), Metal(CGunmetal * 0.7f, 0.6f));
			if (Side < 0)
			{
				Rig.LegL = Leg;
			}
			else
			{
				Rig.LegR = Leg;
			}
		}
		Rig.Body = B.Pivot(Parent, FVector(0.f, 0.f, HipZ));
		B.Part(Rig.Body, EShape::Cube, FVector(0.f, 0.f, 18.f), FVector(90.f, 100.f, 36.f), Metal(CGunmetal, 0.5f));
		B.Part(Rig.Body, EShape::Cube, FVector(0.f, 0.f, 86.f), FVector(110.f, 120.f, 100.f), Metal(Frame, 0.35f));
		B.Part(Rig.Body, EShape::Cube, FVector(0.f, 0.f, 112.f), FVector(112.f, 122.f, 10.f), Paint(TeamColor(Team), 0.5f));
		FMaterialParams Cockpit = Paint(TeamColor(Team), 0.2f);
		Cockpit.Emissive = 6.f;
		B.Part(Rig.Body, EShape::Cube, FVector(56.f, 0.f, 96.f), FVector(6.f, 62.f, 26.f), Cockpit, FRotator::ZeroRotator, false);
		B.Part(Rig.Body, EShape::Cube, FVector(-22.f, 0.f, 160.f), FVector(46.f, 60.f, 40.f), Metal(CGunmetal, 0.5f));
		Rig.Turret = B.Pivot(Rig.Body, FVector::ZeroVector);
		FMaterialParams Plasma = Paint(FLinearColor(1.f, 0.35f, 0.95f), 0.2f);
		Plasma.Emissive = 10.f;
		for (int32 Side = -1; Side <= 1; Side += 2)
		{
			B.Part(Rig.Turret, EShape::Sphere, FVector(0.f, Side * 74.f, 118.f), FVector(52.f, 46.f, 46.f), Metal(Frame, 0.35f));
			B.Part(Rig.Turret, EShape::Cylinder, FVector(62.f, Side * 80.f, 92.f), FVector(24.f, 24.f, 112.f), Metal(CIron), FRotator(-90.f, 0.f, 0.f));
			B.Part(Rig.Turret, EShape::Sphere, FVector(120.f, Side * 80.f, 92.f), FVector(18.f), Plasma, FRotator::ZeroRotator, false);
		}
		Rig.Muzzle = B.Pivot(Rig.Turret, FVector(126.f, 80.f, 92.f));
		Rig.TurretRest = Rig.Turret->GetRelativeLocation();
		Rig.Style = ECWAttackStyle::Cannon;
		Rig.Height = 310.f;
		Rig.StrideLength = 160.f;
	}
}

namespace CWModels
{
	using namespace CWVisual;
	using namespace CWModelsDetail;

	void BuildUnit(AActor* Owner, USceneComponent* Root, FName VisualKey, int32 Team, FCWUnitRig& Rig)
	{
		FCWModelBuilder B;
		B.Owner = Owner;
		B.Mats = &Rig.Materials;
		B.Colors = &Rig.BaseColors;
		const FLinearColor Accent = TeamColor(Team);
		const FString Key = VisualKey.ToString();

		FHumanStyle S;
		S.Accent = Accent;
		if (Key == TEXT("Unit_StoneAxe"))
		{
			S.Torso = CFur;
			S.Legs = CLeather;
			S.Helmet = EHelmet::Band;
			S.Weapon = EWeapon::Axe;
			BuildHuman(B, Root, S, Rig, 1.0f);
		}
		else if (Key == TEXT("Unit_StoneSlinger"))
		{
			S.Torso = CLeather * 1.15f;
			S.Legs = CFur;
			S.Helmet = EHelmet::Hood;
			S.Weapon = EWeapon::Sling;
			BuildHuman(B, Root, S, Rig, 0.95f);
		}
		else if (Key == TEXT("Unit_BeastRider"))
		{
			FBeastStyle Beast;
			Beast.Body = CMammoth;
			Beast.Accent = Accent;
			Beast.Length = 175.f;
			Beast.Width = 105.f;
			Beast.Height = 110.f;
			Beast.LegLen = 72.f;
			Beast.LegThick = 30.f;
			Beast.bMammoth = true;
			USceneComponent* Saddle = BuildQuadruped(B, Root, Beast, Rig);
			USceneComponent* MountBody = Rig.Body;
			S.Torso = CFur;
			S.Helmet = EHelmet::Band;
			S.Weapon = EWeapon::Spear;
			S.bLegs = false;
			BuildHuman(B, Saddle, S, Rig, 0.9f);
			Rig.Body = MountBody;
			Rig.Height = 260.f;
			Rig.StrideLength = 120.f;
		}
		else if (Key == TEXT("Unit_ShieldSword"))
		{
			S.Torso = CSteel;
			S.bMetalTorso = true;
			S.Legs = CLinen * 0.6f;
			S.Helmet = EHelmet::Kettle;
			S.Weapon = EWeapon::Sword;
			S.bShield = true;
			BuildHuman(B, Root, S, Rig, 1.05f);
		}
		else if (Key == TEXT("Unit_Crossbowman"))
		{
			S.Torso = CPadded;
			S.Legs = CLeather;
			S.Helmet = EHelmet::Kettle;
			S.Weapon = EWeapon::Crossbow;
			BuildHuman(B, Root, S, Rig, 1.0f);
		}
		else if (Key == TEXT("Unit_Knight"))
		{
			FBeastStyle Horse;
			Horse.Body = CHorse;
			Horse.Accent = Accent;
			Horse.bCaparison = true;
			USceneComponent* Saddle = BuildQuadruped(B, Root, Horse, Rig);
			USceneComponent* MountBody = Rig.Body;
			S.Torso = CSteel;
			S.bMetalTorso = true;
			S.Legs = CSteel * 0.8f;
			S.Helmet = EHelmet::Great;
			S.Weapon = EWeapon::Lance;
			S.bShield = true;
			S.bLegs = false;
			BuildHuman(B, Saddle, S, Rig, 0.95f);
			Rig.Body = MountBody;
			Rig.Height = 250.f;
			Rig.StrideLength = 140.f;
		}
		else if (Key == TEXT("Unit_Engineer"))
		{
			S.Torso = FLinearColor(0.35f, 0.25f, 0.15f);
			S.Legs = COlive;
			S.Helmet = EHelmet::Steel;
			S.Weapon = EWeapon::Shovel;
			S.bBackpack = true;
			BuildHuman(B, Root, S, Rig, 1.0f);
		}
		else if (Key == TEXT("Unit_Rifleman"))
		{
			S.Torso = COlive;
			S.Legs = COliveDark;
			S.Helmet = EHelmet::Steel;
			S.Weapon = EWeapon::Rifle;
			BuildHuman(B, Root, S, Rig, 1.0f);
		}
		else if (Key == TEXT("Unit_ArmoredCar"))
		{
			BuildArmoredCar(B, Root, Team, Rig);
		}
		else if (Key == TEXT("Unit_RiotTrooper"))
		{
			S.Torso = CRiotBlack * 2.5f;
			S.bMetalTorso = true;
			S.Legs = CRiotBlack * 1.6f;
			S.Helmet = EHelmet::Riot;
			S.Weapon = EWeapon::Baton;
			S.bRiotShield = true;
			BuildHuman(B, Root, S, Rig, 1.05f);
		}
		else if (Key == TEXT("Unit_RocketTrooper"))
		{
			S.Torso = COlive * 1.1f;
			S.Legs = COliveDark;
			S.Helmet = EHelmet::Steel;
			S.Weapon = EWeapon::Launcher;
			S.bBackpack = true;
			BuildHuman(B, Root, S, Rig, 1.0f);
		}
		else if (Key == TEXT("Unit_MainTank"))
		{
			BuildTank(B, Root, Team, Rig);
		}
		else if (Key == TEXT("Unit_PlasmaBlade"))
		{
			S.Torso = CArmorWhite;
			S.bMetalTorso = true;
			S.Legs = CGunmetal;
			S.Helmet = EHelmet::Sleek;
			S.Weapon = EWeapon::EnergyBlade;
			BuildHuman(B, Root, S, Rig, 1.08f);
		}
		else if (Key == TEXT("Unit_LaserTrooper"))
		{
			S.Torso = CArmorWhite * 0.9f;
			S.bMetalTorso = true;
			S.Legs = CGunmetal * 1.2f;
			S.Helmet = EHelmet::Sleek;
			S.Weapon = EWeapon::LaserRifle;
			BuildHuman(B, Root, S, Rig, 1.0f);
		}
		else if (Key == TEXT("Unit_Mech"))
		{
			BuildMech(B, Root, Team, Rig);
		}
		else if (Key.StartsWith(TEXT("Champion_")))
		{
			BuildChampion(B, Root, Team, Key, Rig);
		}
		else
		{
			// 未配置外观：通用人形（醒目的洋红色提示缺少美术）
			S.Torso = FLinearColor(0.9f, 0.1f, 0.8f);
			BuildHuman(B, Root, S, Rig, 1.0f);
		}
	}

	void BuildBase(AActor* Owner, USceneComponent* Root, int32 Age, int32 Team, FCWBaseRig& Rig)
	{
		FCWModelBuilder B;
		B.Owner = Owner;
		B.Mats = &Rig.Materials;
		B.Colors = &Rig.BaseColors;
		const FLinearColor Accent = TeamColor(Team);
		Rig.TurretMounts.Reset();

		if (Age <= 0)
		{
			// 石器时代：土丘、木栅栏、茅草大屋、图腾
			B.Part(Root, EShape::Cylinder, FVector(-20.f, 0.f, 12.f), FVector(640.f, 560.f, 24.f), Paint(CMud, 0.95f));
			for (int32 I = 0; I < 9; ++I)
			{
				const float Y = -260.f + I * 65.f;
				B.Part(Root, EShape::Cylinder, FVector(-300.f, Y, 90.f), FVector(24.f, 24.f, 160.f), Paint(CWood, 0.9f));
				B.Part(Root, EShape::Cone, FVector(-300.f, Y, 185.f), FVector(26.f, 26.f, 30.f), Paint(CWood * 1.2f, 0.9f));
				if (FMath::Abs(Y) > 100.f)
				{
					B.Part(Root, EShape::Cylinder, FVector(270.f, Y, 80.f), FVector(24.f, 24.f, 140.f), Paint(CWood, 0.9f));
					B.Part(Root, EShape::Cone, FVector(270.f, Y, 165.f), FVector(26.f, 26.f, 30.f), Paint(CWood * 1.2f, 0.9f));
				}
			}
			B.Part(Root, EShape::Cylinder, FVector(-60.f, 0.f, 110.f), FVector(270.f, 270.f, 170.f), Paint(CMud, 0.95f));
			B.Part(Root, EShape::Cone, FVector(-60.f, 0.f, 285.f), FVector(340.f, 340.f, 190.f), Paint(CThatch, 0.95f));
			B.Part(Root, EShape::Cube, FVector(78.f, 0.f, 75.f), FVector(10.f, 70.f, 100.f), Paint(CLeatherDark, 0.95f));
			B.Part(Root, EShape::Cylinder, FVector(160.f, 200.f, 160.f), FVector(16.f, 16.f, 320.f), Paint(CWood));
			B.Part(Root, EShape::Cube, FVector(160.f, 238.f, 270.f), FVector(6.f, 80.f, 70.f), Paint(Accent, 0.7f));
			B.Part(Root, EShape::Sphere, FVector(160.f, 200.f, 330.f), FVector(34.f, 30.f, 34.f), Paint(CIvory, 0.5f));
			// 篝火
			B.Part(Root, EShape::Cylinder, FVector(140.f, -170.f, 30.f), FVector(70.f, 70.f, 16.f), Paint(CStone));
			FMaterialParams Fire = Paint(FLinearColor(1.f, 0.45f, 0.08f), 0.5f);
			Fire.Emissive = 6.f;
			B.Part(Root, EShape::Cone, FVector(140.f, -170.f, 62.f), FVector(40.f, 40.f, 50.f), Fire, FRotator::ZeroRotator, false);
			// 炮塔平台
			const FVector Mounts[3] = { FVector(200.f, -150.f, 170.f), FVector(200.f, 150.f, 170.f), FVector(-60.f, 0.f, 380.f) };
			for (int32 I = 0; I < 3; ++I)
			{
				Rig.TurretMounts.Add(Mounts[I]);
				if (I < 2)
				{
					B.Part(Root, EShape::Cube, Mounts[I] - FVector(0.f, 0.f, 12.f), FVector(100.f, 100.f, 18.f), Paint(CWood * 1.1f));
					B.Part(Root, EShape::Cylinder, Mounts[I] - FVector(0.f, 0.f, 90.f), FVector(16.f, 16.f, 150.f), Paint(CWood));
				}
			}
			Rig.Height = 380.f;
		}
		else if (Age == 1)
		{
			// 中世纪：石砌主堡、城墙城门、两座塔楼
			B.Part(Root, EShape::Cube, FVector(-20.f, 0.f, 10.f), FVector(660.f, 600.f, 20.f), Paint(CStone * 0.8f, 0.95f));
			B.Part(Root, EShape::Cube, FVector(-90.f, 0.f, 200.f), FVector(300.f, 280.f, 380.f), Paint(CStone, 0.9f));
			for (int32 I = 0; I < 5; ++I)
			{
				B.Part(Root, EShape::Cube, FVector(-90.f + 125.f, -120.f + I * 60.f, 405.f), FVector(40.f, 34.f, 34.f), Paint(CStone, 0.9f));
				B.Part(Root, EShape::Cube, FVector(-90.f - 125.f, -120.f + I * 60.f, 405.f), FVector(40.f, 34.f, 34.f), Paint(CStone, 0.9f));
			}
			B.Part(Root, EShape::Cube, FVector(230.f, -165.f, 120.f), FVector(70.f, 170.f, 240.f), Paint(CStone * 0.9f, 0.9f));
			B.Part(Root, EShape::Cube, FVector(230.f, 165.f, 120.f), FVector(70.f, 170.f, 240.f), Paint(CStone * 0.9f, 0.9f));
			B.Part(Root, EShape::Cube, FVector(230.f, 0.f, 205.f), FVector(70.f, 160.f, 70.f), Paint(CStone * 0.9f, 0.9f));
			B.Part(Root, EShape::Cube, FVector(262.f, 0.f, 85.f), FVector(8.f, 150.f, 170.f), Paint(CWood * 0.7f, 0.8f));
			for (int32 Side = -1; Side <= 1; Side += 2)
			{
				const float Y = 255.f * Side;
				B.Part(Root, EShape::Cylinder, FVector(220.f, Y, 165.f), FVector(130.f, 130.f, 330.f), Paint(CStone * 0.95f, 0.9f));
				B.Part(Root, EShape::Cone, FVector(220.f, Y, 400.f), FVector(160.f, 160.f, 140.f), Paint(Accent * 0.85f, 0.6f));
				B.Part(Root, EShape::Cube, FVector(-90.f, Y * 0.62f, 330.f), FVector(6.f, 70.f, 110.f), Paint(Accent, 0.7f));
			}
			B.Part(Root, EShape::Cylinder, FVector(-90.f, 0.f, 470.f), FVector(10.f, 10.f, 140.f), Paint(CWood));
			B.Part(Root, EShape::Cube, FVector(-90.f, 40.f, 510.f), FVector(4.f, 80.f, 50.f), Paint(Accent, 0.7f));
			Rig.TurretMounts.Add(FVector(220.f, -255.f, 335.f));
			Rig.TurretMounts.Add(FVector(220.f, 255.f, 335.f));
			Rig.TurretMounts.Add(FVector(-90.f, 0.f, 425.f));
			Rig.Height = 520.f;
		}
		else if (Age == 3)
		{
			// 现代：混凝土指挥中心（斜面防护）、指挥层观察窗、雷达塔、天线、停机坪、防爆墙与两座岗楼
			B.Part(Root, EShape::Cube, FVector(-20.f, 0.f, 10.f), FVector(700.f, 640.f, 20.f), Paint(CConcrete * 0.7f, 0.95f));
			B.Part(Root, EShape::Cube, FVector(-110.f, 0.f, 130.f), FVector(300.f, 320.f, 240.f), Paint(CConcrete * 1.05f, 0.9f));
			B.Part(Root, EShape::Cube, FVector(58.f, 0.f, 100.f), FVector(80.f, 316.f, 200.f), Paint(CConcrete * 0.9f, 0.9f), FRotator(22.f, 0.f, 0.f));
			B.Part(Root, EShape::Cube, FVector(-110.f, 0.f, 248.f), FVector(304.f, 324.f, 10.f), Paint(Accent, 0.5f));
			B.Part(Root, EShape::Cube, FVector(-140.f, 0.f, 295.f), FVector(190.f, 220.f, 90.f), Paint(CConcrete * 1.15f, 0.85f));
			B.Part(Root, EShape::Cube, FVector(-43.f, 0.f, 302.f), FVector(6.f, 200.f, 30.f), Paint(FLinearColor(0.10f, 0.16f, 0.22f), 0.08f), FRotator::ZeroRotator, false);
			// 天线与警示灯
			B.Part(Root, EShape::Cylinder, FVector(-200.f, 80.f, 460.f), FVector(6.f, 6.f, 240.f), Metal(CIron));
			FMaterialParams Beacon = Paint(FLinearColor(1.f, 0.1f, 0.05f), 0.3f);
			Beacon.Emissive = 8.f;
			B.Part(Root, EShape::Sphere, FVector(-200.f, 80.f, 584.f), FVector(14.f), Beacon, FRotator::ZeroRotator, false);
			// 雷达塔：四根支架 + 倾斜碟面
			for (int32 I = 0; I < 4; ++I)
			{
				const float A = I * PI * 0.5f + PI * 0.25f;
				B.Part(Root, EShape::Cylinder, FVector(-300.f + FMath::Cos(A) * 36.f, -230.f + FMath::Sin(A) * 36.f, 160.f), FVector(8.f, 8.f, 300.f), Metal(CGunmetal));
			}
			B.Part(Root, EShape::Cube, FVector(-300.f, -230.f, 312.f), FVector(90.f, 90.f, 12.f), Metal(CGunmetal));
			B.Part(Root, EShape::Sphere, FVector(-300.f, -230.f, 360.f), FVector(150.f, 150.f, 36.f), Metal(CArmorWhite, 0.4f), FRotator(35.f, 0.f, 0.f));
			// 停机坪
			B.Part(Root, EShape::Cylinder, FVector(-270.f, 190.f, 24.f), FVector(180.f, 180.f, 8.f), Paint(FLinearColor(0.12f, 0.12f, 0.13f), 0.9f));
			B.Part(Root, EShape::Cube, FVector(-270.f, 160.f, 29.f), FVector(70.f, 10.f, 4.f), Paint(FLinearColor::White, 0.6f));
			B.Part(Root, EShape::Cube, FVector(-270.f, 220.f, 29.f), FVector(70.f, 10.f, 4.f), Paint(FLinearColor::White, 0.6f));
			B.Part(Root, EShape::Cube, FVector(-270.f, 190.f, 29.f), FVector(10.f, 60.f, 4.f), Paint(FLinearColor::White, 0.6f));
			// 正面防爆墙与电动闸门
			for (int32 Side = -1; Side <= 1; Side += 2)
			{
				B.Part(Root, EShape::Cube, FVector(250.f, 145.f * Side, 95.f), FVector(44.f, 110.f, 170.f), Paint(CConcrete, 0.95f));
				B.Part(Root, EShape::Cube, FVector(250.f, 145.f * Side, 40.f), FVector(70.f, 110.f, 20.f), Paint(CConcrete * 0.9f, 0.95f));
				B.Part(Root, EShape::Cube, FVector(274.f, 145.f * Side, 130.f), FVector(4.f, 110.f, 16.f), Paint(Accent, 0.5f));
				// 岗楼（炮塔平台）
				B.Part(Root, EShape::Cube, FVector(230.f, 255.f * Side, 150.f), FVector(110.f, 110.f, 300.f), Paint(CConcrete * 0.95f, 0.9f));
				B.Part(Root, EShape::Cube, FVector(230.f, 255.f * Side, 296.f), FVector(124.f, 124.f, 12.f), Metal(CGunmetal, 0.6f));
				B.Part(Root, EShape::Cube, FVector(287.f, 255.f * Side, 210.f), FVector(4.f, 70.f, 16.f), Paint(FLinearColor(0.10f, 0.16f, 0.22f), 0.08f), FRotator::ZeroRotator, false);
				for (int32 I = 0; I < 3; ++I)
				{
					B.Part(Root, EShape::Sphere, FVector(310.f, Side * (110.f + I * 40.f), 30.f), FVector(46.f, 36.f, 26.f), Paint(CThatch * 0.7f, 0.95f));
				}
			}
			B.Part(Root, EShape::Cube, FVector(262.f, 0.f, 70.f), FVector(12.f, 180.f, 120.f), Metal(CIron, 0.45f));
			for (int32 I = 0; I < 5; ++I)
			{
				B.Part(Root, EShape::Cube, FVector(270.f, -72.f + I * 36.f, 70.f), FVector(4.f, 16.f, 118.f), Paint(I % 2 == 0 ? FLinearColor(0.9f, 0.75f, 0.1f) : FLinearColor(0.05f, 0.05f, 0.05f), 0.6f));
			}
			Rig.TurretMounts.Add(FVector(230.f, -255.f, 304.f));
			Rig.TurretMounts.Add(FVector(230.f, 255.f, 304.f));
			Rig.TurretMounts.Add(FVector(-140.f, 0.f, 342.f));
			Rig.Height = 580.f;
		}
		else if (Age >= 4)
		{
			// 未来：白色能量尖塔、悬浮光环、两座能量塔、能量闸门
			FMaterialParams Glow = Paint(Accent, 0.2f);
			Glow.Emissive = 4.f;
			FMaterialParams Energy = Paint(CEnergyCyan, 0.2f);
			Energy.Emissive = 6.f;
			B.Part(Root, EShape::Cylinder, FVector(-20.f, 0.f, 8.f), FVector(740.f, 680.f, 16.f), Glow, FRotator::ZeroRotator, false);
			B.Part(Root, EShape::Cylinder, FVector(-20.f, 0.f, 14.f), FVector(720.f, 660.f, 28.f), Metal(CGunmetal * 0.8f, 0.5f));
			// 尖塔：底座 + 锥体 + 发光核心
			B.Part(Root, EShape::Cylinder, FVector(-110.f, 0.f, 160.f), FVector(220.f, 220.f, 280.f), Metal(CArmorWhite, 0.3f));
			B.Part(Root, EShape::Cylinder, FVector(-110.f, 0.f, 230.f), FVector(226.f, 226.f, 14.f), Glow, FRotator::ZeroRotator, false);
			B.Part(Root, EShape::Cone, FVector(-110.f, 0.f, 430.f), FVector(200.f, 200.f, 280.f), Metal(CArmorWhite, 0.3f));
			B.Part(Root, EShape::Sphere, FVector(-110.f, 0.f, 600.f), FVector(54.f), Energy, FRotator::ZeroRotator, false);
			// 悬浮光环（略微倾斜）
			B.Part(Root, EShape::Cylinder, FVector(-110.f, 0.f, 380.f), FVector(320.f, 320.f, 6.f), Glow, FRotator(0.f, 0.f, 6.f), false);
			B.Part(Root, EShape::Cylinder, FVector(-110.f, 0.f, 500.f), FVector(230.f, 230.f, 5.f), Glow, FRotator(0.f, 0.f, -8.f), false);
			// 正面悬挑平台（第三炮位）
			B.Part(Root, EShape::Cube, FVector(30.f, 0.f, 292.f), FVector(110.f, 110.f, 14.f), Metal(CGunmetal, 0.4f));
			B.Part(Root, EShape::Cube, FVector(-10.f, 0.f, 240.f), FVector(40.f, 40.f, 100.f), Metal(CGunmetal, 0.4f), FRotator(-35.f, 0.f, 0.f));
			for (int32 Side = -1; Side <= 1; Side += 2)
			{
				// 能量塔（炮塔平台）
				B.Part(Root, EShape::Cylinder, FVector(220.f, 250.f * Side, 130.f), FVector(100.f, 100.f, 260.f), Metal(CArmorWhite, 0.3f));
				B.Part(Root, EShape::Cylinder, FVector(220.f, 250.f * Side, 190.f), FVector(106.f, 106.f, 12.f), Energy, FRotator::ZeroRotator, false);
				B.Part(Root, EShape::Cylinder, FVector(220.f, 250.f * Side, 266.f), FVector(140.f, 140.f, 12.f), Metal(CGunmetal, 0.4f));
				// 能量闸门两侧的发射柱
				B.Part(Root, EShape::Cube, FVector(262.f, 110.f * Side, 90.f), FVector(30.f, 30.f, 180.f), Metal(CArmorWhite, 0.3f));
				B.Part(Root, EShape::Cube, FVector(262.f, 110.f * Side, 186.f), FVector(34.f, 34.f, 12.f), Glow, FRotator::ZeroRotator, false);
			}
			FMaterialParams Barrier = Paint(CEnergyCyan, 0.2f);
			Barrier.Emissive = 2.5f;
			B.Part(Root, EShape::Cube, FVector(262.f, 0.f, 90.f), FVector(6.f, 190.f, 160.f), Barrier, FRotator::ZeroRotator, false);
			Rig.TurretMounts.Add(FVector(220.f, -250.f, 272.f));
			Rig.TurretMounts.Add(FVector(220.f, 250.f, 272.f));
			Rig.TurretMounts.Add(FVector(40.f, 0.f, 300.f));
			Rig.Height = 640.f;
		}
		else
		{
			// 工业时代：砖砌工厂、烟囱、钢制城门、混凝土碉堡、水塔
			B.Part(Root, EShape::Cube, FVector(-20.f, 0.f, 10.f), FVector(680.f, 620.f, 20.f), Paint(CConcrete * 0.8f, 0.95f));
			B.Part(Root, EShape::Cube, FVector(-90.f, 0.f, 140.f), FVector(340.f, 300.f, 260.f), Paint(CBrick, 0.9f));
			for (int32 I = 0; I < 3; ++I)
			{
				B.Part(Root, EShape::Cube, FVector(-200.f + I * 110.f, 0.f, 290.f), FVector(90.f, 300.f, 60.f), Paint(CIron, 0.6f), FRotator(0.f, 0.f, 0.f));
				B.Part(Root, EShape::Cube, FVector(-160.f + I * 110.f, 0.f, 300.f), FVector(8.f, 290.f, 50.f), Paint(FLinearColor(0.55f, 0.75f, 0.85f), 0.1f));
			}
			for (int32 Side = -1; Side <= 1; Side += 2)
			{
				B.Part(Root, EShape::Cylinder, FVector(-190.f, 95.f * Side, 330.f), FVector(52.f, 52.f, 360.f), Paint(CBrick * 0.85f, 0.9f));
				B.Part(Root, EShape::Cylinder, FVector(-190.f, 95.f * Side, 515.f), FVector(60.f, 60.f, 16.f), Paint(CIron));
			}
			B.Part(Root, EShape::Cube, FVector(235.f, -190.f, 90.f), FVector(80.f, 220.f, 180.f), Paint(CConcrete, 0.95f));
			B.Part(Root, EShape::Cube, FVector(235.f, 190.f, 90.f), FVector(80.f, 220.f, 180.f), Paint(CConcrete, 0.95f));
			B.Part(Root, EShape::Cube, FVector(260.f, 0.f, 80.f), FVector(14.f, 160.f, 160.f), Metal(CIron, 0.45f));
			B.Part(Root, EShape::Cube, FVector(268.f, 0.f, 120.f), FVector(4.f, 160.f, 20.f), Paint(Accent, 0.5f));
			B.Part(Root, EShape::Cylinder, FVector(40.f, -230.f, 380.f), FVector(110.f, 110.f, 90.f), Metal(CSteel * 0.8f, 0.5f));
			for (int32 I = 0; I < 4; ++I)
			{
				const float A = I * PI * 0.5f + PI * 0.25f;
				B.Part(Root, EShape::Cylinder, FVector(40.f + FMath::Cos(A) * 40.f, -230.f + FMath::Sin(A) * 40.f, 170.f), FVector(10.f, 10.f, 330.f), Metal(CIron));
			}
			B.Part(Root, EShape::Cube, FVector(-90.f, 0.f, 230.f), FVector(6.f, 200.f, 50.f), Paint(Accent, 0.6f));
			Rig.TurretMounts.Add(FVector(235.f, -190.f, 182.f));
			Rig.TurretMounts.Add(FVector(235.f, 190.f, 182.f));
			Rig.TurretMounts.Add(FVector(-60.f, 0.f, 330.f));
			Rig.Height = 520.f;
		}
	}

	void BuildTurret(AActor* Owner, USceneComponent* Mount, FName VisualKey, int32 Team, FCWTurretRig& Rig)
	{
		FCWModelBuilder B;
		B.Owner = Owner;
		const FLinearColor Accent = TeamColor(Team);
		const FString Key = VisualKey.ToString();
		Rig.Root = B.Pivot(Mount, FVector::ZeroVector);
		if (Key == TEXT("Turret_RockTower"))
		{
			B.Part(Rig.Root, EShape::Cube, FVector(0.f, 0.f, 12.f), FVector(80.f, 70.f, 24.f), Paint(CWood));
			B.Part(Rig.Root, EShape::Cube, FVector(-10.f, 26.f, 50.f), FVector(12.f, 10.f, 70.f), Paint(CWood));
			B.Part(Rig.Root, EShape::Cube, FVector(-10.f, -26.f, 50.f), FVector(12.f, 10.f, 70.f), Paint(CWood));
			Rig.Aim = B.Pivot(Rig.Root, FVector(-10.f, 0.f, 70.f), FRotator(-30.f, 0.f, 0.f));
			B.Part(Rig.Aim, EShape::Cylinder, FVector(-40.f, 0.f, 0.f), FVector(9.f, 9.f, 90.f), Paint(CWood * 1.2f), FRotator(90.f, 0.f, 0.f));
			B.Part(Rig.Aim, EShape::Sphere, FVector(-85.f, 0.f, 6.f), FVector(26.f, 26.f, 22.f), Paint(CStone));
			Rig.Muzzle = B.Pivot(Rig.Aim, FVector(-85.f, 0.f, 10.f));
			B.Part(Rig.Root, EShape::Cube, FVector(30.f, 0.f, 30.f), FVector(6.f, 40.f, 30.f), Paint(Accent, 0.7f));
		}
		else if (Key == TEXT("Turret_ArrowTower"))
		{
			B.Part(Rig.Root, EShape::Cylinder, FVector(0.f, 0.f, 20.f), FVector(80.f, 80.f, 40.f), Paint(CWood));
			B.Part(Rig.Root, EShape::Cylinder, FVector(0.f, 0.f, 45.f), FVector(90.f, 90.f, 8.f), Paint(Accent * 0.8f));
			Rig.Aim = B.Pivot(Rig.Root, FVector(0.f, 0.f, 60.f));
			B.Part(Rig.Aim, EShape::Cone, FVector(0.f, 0.f, 25.f), FVector(32.f, 32.f, 50.f), Paint(CPadded));
			B.Part(Rig.Aim, EShape::Sphere, FVector(0.f, 0.f, 60.f), FVector(22.f, 22.f, 24.f), Paint(CSkin));
			B.Part(Rig.Aim, EShape::Cylinder, FVector(16.f, 0.f, 35.f), FVector(4.f, 4.f, 60.f), Paint(CWood));
			Rig.Muzzle = B.Pivot(Rig.Aim, FVector(22.f, 0.f, 40.f));
		}
		else if (Key == TEXT("Turret_Ballista"))
		{
			B.Part(Rig.Root, EShape::Cube, FVector(0.f, 0.f, 15.f), FVector(70.f, 70.f, 30.f), Paint(CWood));
			Rig.Aim = B.Pivot(Rig.Root, FVector(0.f, 0.f, 45.f));
			B.Part(Rig.Aim, EShape::Cube, FVector(20.f, 0.f, 0.f), FVector(120.f, 14.f, 14.f), Paint(CWood * 1.1f));
			B.Part(Rig.Aim, EShape::Cube, FVector(55.f, 0.f, 0.f), FVector(10.f, 130.f, 10.f), Paint(CWood * 0.8f));
			B.Part(Rig.Aim, EShape::Cylinder, FVector(40.f, 0.f, 8.f), FVector(6.f, 6.f, 90.f), Metal(CIron), FRotator(-90.f, 0.f, 0.f));
			Rig.Muzzle = B.Pivot(Rig.Aim, FVector(85.f, 0.f, 8.f));
			B.Part(Rig.Root, EShape::Cube, FVector(-30.f, 0.f, 50.f), FVector(6.f, 50.f, 40.f), Paint(Accent, 0.7f));
		}
		else if (Key == TEXT("Turret_MachineGun"))
		{
			for (int32 I = 0; I < 7; ++I)
			{
				const float A = -PI * 0.6f + I * PI * 0.2f;
				B.Part(Rig.Root, EShape::Sphere, FVector(FMath::Cos(A) * 45.f, FMath::Sin(A) * 45.f, 18.f), FVector(40.f, 30.f, 26.f), Paint(CThatch * 0.8f, 0.95f));
			}
			Rig.Aim = B.Pivot(Rig.Root, FVector(0.f, 0.f, 40.f));
			B.Part(Rig.Aim, EShape::Cube, FVector(0.f, 0.f, 0.f), FVector(40.f, 16.f, 18.f), Metal(CIron));
			B.Part(Rig.Aim, EShape::Cylinder, FVector(40.f, 0.f, 2.f), FVector(6.f, 6.f, 60.f), Metal(CIron), FRotator(-90.f, 0.f, 0.f));
			B.Part(Rig.Aim, EShape::Cube, FVector(10.f, 0.f, 16.f), FVector(4.f, 30.f, 16.f), Paint(Accent, 0.6f));
			Rig.Muzzle = B.Pivot(Rig.Aim, FVector(72.f, 0.f, 2.f));
		}
		else if (Key == TEXT("Turret_Autocannon"))
		{
			// 双管机关炮：装甲转台 + 两根长炮管
			B.Part(Rig.Root, EShape::Cylinder, FVector(0.f, 0.f, 14.f), FVector(90.f, 90.f, 28.f), Metal(CGunmetal, 0.5f));
			B.Part(Rig.Root, EShape::Cylinder, FVector(0.f, 0.f, 30.f), FVector(94.f, 94.f, 6.f), Paint(Accent, 0.5f));
			Rig.Aim = B.Pivot(Rig.Root, FVector(0.f, 0.f, 58.f), FRotator(8.f, 0.f, 0.f));
			B.Part(Rig.Aim, EShape::Cube, FVector(0.f, 0.f, 0.f), FVector(64.f, 50.f, 40.f), Metal(COlive, 0.5f));
			for (int32 Side = -1; Side <= 1; Side += 2)
			{
				B.Part(Rig.Aim, EShape::Cylinder, FVector(62.f, Side * 13.f, 4.f), FVector(8.f, 8.f, 90.f), Metal(CIron), FRotator(-90.f, 0.f, 0.f));
				B.Part(Rig.Aim, EShape::Cylinder, FVector(104.f, Side * 13.f, 4.f), FVector(12.f, 12.f, 12.f), Metal(CIron), FRotator(-90.f, 0.f, 0.f));
			}
			Rig.Muzzle = B.Pivot(Rig.Aim, FVector(112.f, 0.f, 4.f));
		}
		else if (Key == TEXT("Turret_MissileBattery"))
		{
			// 导弹发射架：倾斜的箱式发射器，正面露出 2×3 弹头
			B.Part(Rig.Root, EShape::Cube, FVector(0.f, 0.f, 14.f), FVector(90.f, 80.f, 28.f), Metal(CGunmetal, 0.5f));
			Rig.Aim = B.Pivot(Rig.Root, FVector(0.f, 0.f, 62.f), FRotator(25.f, 0.f, 0.f));
			B.Part(Rig.Aim, EShape::Cube, FVector(0.f, 0.f, 0.f), FVector(100.f, 76.f, 52.f), Metal(COlive, 0.55f));
			B.Part(Rig.Aim, EShape::Cube, FVector(0.f, 0.f, 28.f), FVector(102.f, 78.f, 6.f), Paint(Accent, 0.5f));
			for (int32 Row = 0; Row < 2; ++Row)
			{
				for (int32 Col = 0; Col < 3; ++Col)
				{
					B.Part(Rig.Aim, EShape::Cone, FVector(54.f, -22.f + Col * 22.f, -10.f + Row * 20.f), FVector(14.f, 14.f, 16.f), Paint(FLinearColor(0.85f, 0.85f, 0.85f), 0.5f), FRotator(-90.f, 0.f, 0.f));
				}
			}
			Rig.Muzzle = B.Pivot(Rig.Aim, FVector(62.f, 0.f, 0.f));
		}
		else if (Key == TEXT("Turret_LaserTower"))
		{
			// 激光塔：白色立柱 + 发光聚焦晶体
			FMaterialParams Crystal = Paint(CEnergyCyan, 0.15f);
			Crystal.Emissive = 10.f;
			B.Part(Rig.Root, EShape::Cylinder, FVector(0.f, 0.f, 12.f), FVector(80.f, 80.f, 24.f), Metal(CGunmetal, 0.4f));
			B.Part(Rig.Root, EShape::Cylinder, FVector(0.f, 0.f, 50.f), FVector(36.f, 36.f, 60.f), Metal(CArmorWhite, 0.3f));
			B.Part(Rig.Root, EShape::Cylinder, FVector(0.f, 0.f, 40.f), FVector(40.f, 40.f, 6.f), Crystal, FRotator::ZeroRotator, false);
			Rig.Aim = B.Pivot(Rig.Root, FVector(0.f, 0.f, 92.f));
			B.Part(Rig.Aim, EShape::Cube, FVector(4.f, 0.f, 0.f), FVector(60.f, 34.f, 30.f), Metal(CArmorWhite, 0.3f));
			B.Part(Rig.Aim, EShape::Cylinder, FVector(44.f, 0.f, 0.f), FVector(14.f, 14.f, 34.f), Metal(CGunmetal, 0.4f), FRotator(-90.f, 0.f, 0.f));
			B.Part(Rig.Aim, EShape::Sphere, FVector(64.f, 0.f, 0.f), FVector(18.f), Crystal, FRotator::ZeroRotator, false);
			B.Part(Rig.Aim, EShape::Cube, FVector(-10.f, 0.f, 18.f), FVector(30.f, 36.f, 6.f), Paint(Accent, 0.5f));
			Rig.Muzzle = B.Pivot(Rig.Aim, FVector(70.f, 0.f, 0.f));
		}
		else if (Key == TEXT("Turret_IonCannon"))
		{
			// 离子炮：重型底座、三叉聚能器、等离子核心
			FMaterialParams Core = Paint(FLinearColor(0.75f, 0.45f, 1.f), 0.15f);
			Core.Emissive = 12.f;
			B.Part(Rig.Root, EShape::Cylinder, FVector(0.f, 0.f, 16.f), FVector(110.f, 110.f, 32.f), Metal(CGunmetal, 0.4f));
			B.Part(Rig.Root, EShape::Cylinder, FVector(0.f, 0.f, 34.f), FVector(114.f, 114.f, 6.f), Paint(Accent, 0.5f));
			Rig.Aim = B.Pivot(Rig.Root, FVector(0.f, 0.f, 72.f), FRotator(10.f, 0.f, 0.f));
			B.Part(Rig.Aim, EShape::Sphere, FVector(0.f, 0.f, 0.f), FVector(76.f, 70.f, 64.f), Metal(CArmorWhite, 0.3f));
			B.Part(Rig.Aim, EShape::Cylinder, FVector(50.f, 0.f, 0.f), FVector(30.f, 30.f, 40.f), Metal(CGunmetal, 0.4f), FRotator(-90.f, 0.f, 0.f));
			for (int32 I = 0; I < 3; ++I)
			{
				const float A = I * 2.f * PI / 3.f;
				B.Part(Rig.Aim, EShape::Cube, FVector(84.f, FMath::Cos(A) * 18.f, FMath::Sin(A) * 18.f), FVector(50.f, 8.f, 8.f), Metal(CArmorWhite, 0.3f));
			}
			B.Part(Rig.Aim, EShape::Sphere, FVector(96.f, 0.f, 0.f), FVector(22.f), Core, FRotator::ZeroRotator, false);
			Rig.Muzzle = B.Pivot(Rig.Aim, FVector(110.f, 0.f, 0.f));
		}
		else
		{
			// 加农炮台（及默认）
			B.Part(Rig.Root, EShape::Cube, FVector(-10.f, 0.f, 20.f), FVector(80.f, 60.f, 30.f), Paint(CWood * 0.9f));
			B.Part(Rig.Root, EShape::Cylinder, FVector(-10.f, 40.f, 30.f), FVector(55.f, 55.f, 10.f), Paint(CWood), FRotator(0.f, 0.f, 90.f));
			B.Part(Rig.Root, EShape::Cylinder, FVector(-10.f, -40.f, 30.f), FVector(55.f, 55.f, 10.f), Paint(CWood), FRotator(0.f, 0.f, 90.f));
			Rig.Aim = B.Pivot(Rig.Root, FVector(0.f, 0.f, 45.f), FRotator(12.f, 0.f, 0.f));
			B.Part(Rig.Aim, EShape::Cylinder, FVector(30.f, 0.f, 0.f), FVector(26.f, 26.f, 110.f), Metal(CIron * 0.8f, 0.4f), FRotator(-90.f, 0.f, 0.f));
			B.Part(Rig.Aim, EShape::Cylinder, FVector(84.f, 0.f, 0.f), FVector(32.f, 32.f, 8.f), Metal(CIron * 0.8f, 0.4f), FRotator(-90.f, 0.f, 0.f));
			Rig.Muzzle = B.Pivot(Rig.Aim, FVector(90.f, 0.f, 0.f));
			B.Part(Rig.Root, EShape::Cube, FVector(-45.f, 0.f, 45.f), FVector(6.f, 40.f, 30.f), Paint(Accent, 0.7f));
		}
	}

	FProjectileLook GetProjectileLook(FName VisualKey)
	{
		FProjectileLook L;
		const FString Key = VisualKey.ToString();
		if (Key == TEXT("Unit_StoneSlinger"))
		{
			L.Shape = EShape::Sphere; L.Size = FVector(10.f); L.Color = CStone; L.ArcHeight = 70.f;
		}
		else if (Key == TEXT("Unit_Crossbowman"))
		{
			L.Shape = EShape::Cylinder; L.Size = FVector(3.f, 3.f, 45.f); L.Color = CWood; L.ArcHeight = 25.f; L.bAlignToVelocity = true;
		}
		else if (Key == TEXT("Unit_Rifleman") || Key == TEXT("Turret_MachineGun") || Key == TEXT("Unit_ArmoredCar"))
		{
			L.Shape = EShape::Cylinder; L.Size = FVector(2.5f, 2.5f, 70.f); L.Color = FLinearColor(1.f, 0.8f, 0.3f); L.Emissive = 12.f; L.bAlignToVelocity = true;
		}
		else if (Key == TEXT("Turret_RockTower"))
		{
			L.Shape = EShape::Sphere; L.Size = FVector(28.f); L.Color = CStone; L.ArcHeight = 220.f;
		}
		else if (Key == TEXT("Turret_ArrowTower"))
		{
			L.Shape = EShape::Cylinder; L.Size = FVector(3.f, 3.f, 55.f); L.Color = CWood; L.ArcHeight = 70.f; L.bAlignToVelocity = true;
		}
		else if (Key == TEXT("Turret_Ballista"))
		{
			L.Shape = EShape::Cylinder; L.Size = FVector(6.f, 6.f, 100.f); L.Color = CWood * 0.8f; L.ArcHeight = 35.f; L.bAlignToVelocity = true;
		}
		else if (Key == TEXT("Turret_Cannon"))
		{
			L.Shape = EShape::Sphere; L.Size = FVector(22.f); L.Color = CIron; L.ArcHeight = 140.f;
		}
		else if (Key == TEXT("Unit_RocketTrooper") || Key == TEXT("Turret_MissileBattery"))
		{
			// 火箭弹：发光尾焰的细长弹体，轻微抛物线
			L.Shape = EShape::Cylinder; L.Size = FVector(9.f, 9.f, 60.f); L.Color = FLinearColor(1.f, 0.55f, 0.15f); L.Emissive = 6.f; L.ArcHeight = 40.f; L.bAlignToVelocity = true;
		}
		else if (Key == TEXT("Unit_MainTank"))
		{
			L.Shape = EShape::Cylinder; L.Size = FVector(12.f, 12.f, 40.f); L.Color = FLinearColor(1.f, 0.7f, 0.3f); L.Emissive = 8.f; L.ArcHeight = 20.f; L.bAlignToVelocity = true;
		}
		else if (Key == TEXT("Turret_Autocannon"))
		{
			L.Shape = EShape::Cylinder; L.Size = FVector(5.f, 5.f, 80.f); L.Color = FLinearColor(1.f, 0.7f, 0.25f); L.Emissive = 14.f; L.bAlignToVelocity = true;
		}
		else if (Key == TEXT("Unit_LaserTrooper") || Key == TEXT("Turret_LaserTower"))
		{
			// 激光脉冲：细长高亮光束，直线飞行
			L.Shape = EShape::Cylinder; L.Size = FVector(4.f, 4.f, 130.f); L.Color = CEnergyCyan; L.Emissive = 25.f; L.bAlignToVelocity = true;
		}
		else if (Key == TEXT("Unit_Mech") || Key == TEXT("Turret_IonCannon"))
		{
			// 等离子球
			L.Shape = EShape::Sphere; L.Size = FVector(30.f); L.Color = FLinearColor(0.85f, 0.4f, 1.f); L.Emissive = 20.f; L.ArcHeight = 15.f;
		}
		return L;
	}
}
