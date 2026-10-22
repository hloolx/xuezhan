#include "View/CWEraArt.h"

#include "Animation/AnimSequence.h"
#include "Components/SkeletalMeshComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Data/CWGameDataSubsystem.h"
#include "Dom/JsonObject.h"
#include "Engine/GameInstance.h"
#include "Engine/StaticMesh.h"
#include "Engine/SkeletalMesh.h"
#include "GameFramework/Actor.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Misc/CommandLine.h"
#include "Misc/FileHelper.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "View/CWModels.h"
#include "View/CWSmoothUnitAnimInstance.h"

namespace
{
	const cw::GameData* DataFor(AActor* Owner)
	{
		const UGameInstance* Game = Owner ? Owner->GetGameInstance() : nullptr;
		const UCWGameDataSubsystem* Data = Game ? Game->GetSubsystem<UCWGameDataSubsystem>() : nullptr;
		return Data && Data->IsLoaded() ? &Data->GetData() : nullptr;
	}

	bool Flag(const TSharedPtr<FJsonObject>& Object, const TCHAR* Field)
	{
		bool Value = false;
		return Object->TryGetBoolField(Field, Value) && Value;
	}

	bool ArtPath(const FString& Path)
	{
		return Path.StartsWith(TEXT("/Game/ArtPilot/")) && !Path.Contains(TEXT(".."));
	}

	bool VectorValue(const TSharedPtr<FJsonValue>& Value, FVector& Out)
	{
		const TArray<TSharedPtr<FJsonValue>>* Numbers = nullptr;
		if (!Value || !Value->TryGetArray(Numbers) || Numbers->Num() != 3) return false;
		for (int32 Axis = 0; Axis < 3; ++Axis)
		{
			double Number;
			if (!(*Numbers)[Axis]->TryGetNumber(Number) || !FMath::IsFinite(Number) || FMath::Abs(Number) > 10000.) return false;
			Out[Axis] = Number;
		}
		return true;
	}

	bool VectorField(const TSharedPtr<FJsonObject>& Object, const TCHAR* Field, FVector& Out)
	{
		return !Object->HasField(Field) || VectorValue(Object->TryGetField(Field), Out);
	}

	bool ReadTransform(const TSharedPtr<FJsonObject>& Object, FTransform& Out)
	{
		FVector Location = FVector::ZeroVector, Rotation = FVector::ZeroVector;
		double Scale = 1.;
		if (Object->HasField(TEXT("uniform_scale")) && !Object->TryGetNumberField(TEXT("uniform_scale"), Scale)) return false;
		if (!FMath::IsFinite(Scale) || Scale <= 0. || Scale > 10. ||
			!VectorField(Object, TEXT("translation_cm"), Location) || !VectorField(Object, TEXT("rotation_degrees"), Rotation)) return false;
		Out = FTransform(FRotator(Rotation.X, Rotation.Y, Rotation.Z), Location, FVector(Scale));
		return true;
	}

	struct FPart
	{
		FString Id;
		int32 Parent = INDEX_NONE;
		UStaticMesh* Mesh = nullptr; // Omitted only for an actual assembly pivot.
		FTransform Transform = FTransform::Identity;
		FTransform AssemblyTransform = FTransform::Identity;
		TMap<int32, UMaterialInterface*> Materials;
	};

	struct FChannel
	{
		int32 Part = INDEX_NONE;
		int32 MaterialSlot = INDEX_NONE;
		FCWEraMotionChannel Motion;
	};

	struct FSkeletalPart
	{
		FString Id;
		int32 Parent = INDEX_NONE; // Static assembly parent; bow/string share this skeleton.
		USkeletalMesh* Mesh = nullptr;
		UAnimSequence* Ready = nullptr;
		UAnimSequence* Fire = nullptr;
		FTransform Transform = FTransform::Identity;
		TMap<int32, UMaterialInterface*> Materials;
	};

	bool ReadParts(const TSharedPtr<FJsonObject>& Config, int32 Team, TArray<FPart>& Parts, FBox& Bounds)
	{
		const TArray<TSharedPtr<FJsonValue>>* Values = nullptr;
		if (!Config->TryGetArrayField(TEXT("parts"), Values) || Values->IsEmpty() || Values->Num() > 48) return false;
		TMap<FString, int32> Ids;
		for (const auto& Value : *Values)
		{
			const TSharedPtr<FJsonObject>* Object = nullptr;
			FPart Part;
			FString Path, Parent;
			if (!Value->TryGetObject(Object) || !(*Object)->TryGetStringField(TEXT("id"), Part.Id) ||
				Part.Id.IsEmpty() || Ids.Contains(Part.Id) || !ReadTransform(*Object, Part.Transform)) return false;
			if ((*Object)->TryGetStringField(TEXT("parent_part"), Parent) && !Parent.IsEmpty())
			{
				const int32* Index = Ids.Find(Parent);
				if (!Index) return false;
				Part.Parent = *Index;
			}
			Part.AssemblyTransform = Part.Parent == INDEX_NONE ? Part.Transform : Part.Transform * Parts[Part.Parent].AssemblyTransform;
			if ((*Object)->HasField(TEXT("static_mesh")))
			{
				if (!(*Object)->TryGetStringField(TEXT("static_mesh"), Path) || !ArtPath(Path)) return false;
				Part.Mesh = LoadObject<UStaticMesh>(nullptr, *Path);
				if (!Part.Mesh || Part.Mesh->GetStaticMaterials().IsEmpty()) return false;
				for (int32 Slot = 0; Slot < Part.Mesh->GetStaticMaterials().Num(); ++Slot)
					if (!Part.Mesh->GetMaterial(Slot)) return false;
				const FBoxSphereBounds MeshBounds = Part.Mesh->GetBounds();
				Bounds += FBox(MeshBounds.Origin - MeshBounds.BoxExtent, MeshBounds.Origin + MeshBounds.BoxExtent).TransformBy(Part.AssemblyTransform);
			}
			const TArray<TSharedPtr<FJsonValue>>* Materials = nullptr;
			if ((*Object)->TryGetArrayField(TEXT("team_materials"), Materials))
			{
				if (!Part.Mesh) return false;
				for (const auto& MaterialValue : *Materials)
				{
					const TSharedPtr<FJsonObject>* Material = nullptr;
					int32 Slot;
					if (!MaterialValue->TryGetObject(Material) || !(*Material)->TryGetNumberField(TEXT("slot"), Slot) ||
						Slot < 0 || Slot >= Part.Mesh->GetStaticMaterials().Num() || Part.Materials.Contains(Slot) ||
						!(*Material)->TryGetStringField(TEXT("path"), Path) || !ArtPath(Path)) return false;
					FString RedPath;
					if ((*Material)->TryGetStringField(TEXT("red_path"), RedPath))
					{
						if (!ArtPath(RedPath)) return false;
						if (Team == 1) Path = RedPath;
					}
					UMaterialInterface* Loaded = LoadObject<UMaterialInterface>(nullptr, *Path);
					if (!Loaded) return false;
					Part.Materials.Add(Slot, Loaded);
				}
			}
			Ids.Add(Part.Id, Parts.Num());
			Parts.Add(MoveTemp(Part));
		}
		return Bounds.IsValid && Bounds.Max.Z > 0.;
	}

	int32 PartIndex(const TArray<FPart>& Parts, const FString& Id)
	{
		return Parts.IndexOfByPredicate([&](const FPart& Part) { return Part.Id == Id; });
	}

	bool ReadSkeletalParts(const TSharedPtr<FJsonObject>& Config, const TArray<FPart>& Parts,
		int32 Team, float Duration, TArray<FSkeletalPart>& Result)
	{
		if (!Config->HasField(TEXT("skeletal_parts"))) return true;
		const TArray<TSharedPtr<FJsonValue>>* Values = nullptr;
		if (!Config->TryGetArrayField(TEXT("skeletal_parts"), Values) || Values->Num() > 4) return false;
		TSet<FString> Ids;
		for (const auto& Value : *Values)
		{
			const TSharedPtr<FJsonObject>* Object = nullptr;
			const TSharedPtr<FJsonObject>* Clips = nullptr;
			FSkeletalPart Part;
			FString Parent, MeshPath, ReadyPath, FirePath;
			if (!Value->TryGetObject(Object) || !(*Object)->TryGetStringField(TEXT("id"), Part.Id) ||
				Part.Id.IsEmpty() || Ids.Contains(Part.Id) || PartIndex(Parts, Part.Id) != INDEX_NONE ||
				!ReadTransform(*Object, Part.Transform) ||
				!(*Object)->TryGetStringField(TEXT("parent_part"), Parent) ||
				!(*Object)->TryGetStringField(TEXT("skeletal_mesh"), MeshPath) || !ArtPath(MeshPath) ||
				!(*Object)->TryGetObjectField(TEXT("animations"), Clips) ||
				!(*Clips)->TryGetStringField(TEXT("Ready"), ReadyPath) || !ArtPath(ReadyPath) ||
				!(*Clips)->TryGetStringField(TEXT("Fire"), FirePath) || !ArtPath(FirePath)) return false;
			Part.Parent = PartIndex(Parts, Parent);
			if (Part.Parent == INDEX_NONE) return false;
			Part.Mesh = LoadObject<USkeletalMesh>(nullptr, *MeshPath);
			Part.Ready = LoadObject<UAnimSequence>(nullptr, *ReadyPath);
			Part.Fire = LoadObject<UAnimSequence>(nullptr, *FirePath);
			if (!Part.Mesh || !Part.Mesh->GetSkeleton() || !Part.Ready || !Part.Fire ||
				Part.Ready == Part.Fire || Part.Ready->GetSkeleton() != Part.Mesh->GetSkeleton() ||
				Part.Fire->GetSkeleton() != Part.Mesh->GetSkeleton() || Part.Ready->GetPlayLength() <= 0.f ||
				!FMath::IsNearlyEqual(Part.Fire->GetPlayLength(), Duration, 0.002f) ||
				Part.Ready->bEnableRootMotion || Part.Fire->bEnableRootMotion ||
				Part.Mesh->GetMaterials().IsEmpty()) return false;
			for (const FSkeletalMaterial& Material : Part.Mesh->GetMaterials())
				if (!Material.MaterialInterface) return false;
			const TArray<TSharedPtr<FJsonValue>>* Materials = nullptr;
			if ((*Object)->TryGetArrayField(TEXT("team_materials"), Materials))
			{
				for (const auto& MaterialValue : *Materials)
				{
					const TSharedPtr<FJsonObject>* Material = nullptr;
					FString Path, RedPath;
					int32 Slot;
					if (!MaterialValue->TryGetObject(Material) || !(*Material)->TryGetNumberField(TEXT("slot"), Slot) ||
						Slot < 0 || Slot >= Part.Mesh->GetMaterials().Num() || Part.Materials.Contains(Slot) ||
						!(*Material)->TryGetStringField(TEXT("path"), Path) || !ArtPath(Path)) return false;
					if ((*Material)->TryGetStringField(TEXT("red_path"), RedPath))
					{
						if (!ArtPath(RedPath)) return false;
						if (Team == 1) Path = RedPath;
					}
					UMaterialInterface* Loaded = LoadObject<UMaterialInterface>(nullptr, *Path);
					if (!Loaded) return false;
					Part.Materials.Add(Slot, Loaded);
				}
			}
			Ids.Add(Part.Id);
			Result.Add(MoveTemp(Part));
		}
		return true;
	}

	bool MovesMesh(const TArray<FPart>& Parts, int32 Index)
	{
		for (int32 Mesh = 0; Mesh < Parts.Num(); ++Mesh)
		{
			if (!Parts[Mesh].Mesh) continue;
			for (int32 Parent = Mesh; Parent != INDEX_NONE; Parent = Parts[Parent].Parent)
				if (Parent == Index) return true;
		}
		return false;
	}

	TArray<USceneComponent*> BuildParts(AActor* Owner, USceneComponent* Parent, const TArray<FPart>& Parts, int32 Team)
	{
		TArray<USceneComponent*> Components;
		for (const FPart& Part : Parts)
		{
			USceneComponent* Component;
			if (Part.Mesh)
			{
				auto* Mesh = NewObject<UStaticMeshComponent>(Owner);
				Mesh->SetStaticMesh(Part.Mesh);
				Mesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
				Mesh->SetGenerateOverlapEvents(false);
				for (const auto& Material : Part.Materials)
				{
					UMaterialInstanceDynamic* Instance = Mesh->CreateDynamicMaterialInstance(Material.Key, Material.Value);
					Instance->SetVectorParameterValue(TEXT("TeamColor"), CWVisual::TeamColor(Team));
					Instance->SetScalarParameterValue(TEXT("TeamColorStrength"), 1.f);
				}
				Component = Mesh;
			}
			else Component = NewObject<USceneComponent>(Owner);
			Owner->AddInstanceComponent(Component);
			Component->SetMobility(EComponentMobility::Movable);
			Component->SetupAttachment(Part.Parent == INDEX_NONE ? Parent : Components[Part.Parent]);
			Component->SetRelativeTransform(Part.Transform);
			Component->SetComponentTickEnabled(false);
			Component->RegisterComponent();
			Components.Add(Component);
		}
		return Components;
	}

	bool ReadChannels(const TSharedPtr<FJsonObject>& Config, const TArray<FPart>& Parts, float Duration, TArray<FChannel>& Channels)
	{
		const TArray<TSharedPtr<FJsonValue>>* Values = nullptr;
		if (!Config->TryGetArrayField(TEXT("channels"), Values) || Values->Num() > 48) return false;
		TSet<int32> UsedParts;
		for (const auto& Value : *Values)
		{
			const TSharedPtr<FJsonObject>* Object = nullptr;
			const TArray<TSharedPtr<FJsonValue>>* Frames = nullptr;
			FChannel Channel;
			FString Id, Parameter;
			if (!Value->TryGetObject(Object) || !(*Object)->TryGetStringField(TEXT("part"), Id)) return false;
			Channel.Part = PartIndex(Parts, Id);
			if (Channel.Part == INDEX_NONE || UsedParts.Contains(Channel.Part) || !MovesMesh(Parts, Channel.Part)) return false;
			UsedParts.Add(Channel.Part);
			if ((*Object)->TryGetStringField(TEXT("scalar_parameter"), Parameter))
			{
				const FPart& Part = Parts[Channel.Part];
				if (Parameter.IsEmpty() || !Part.Mesh || !(*Object)->TryGetNumberField(TEXT("material_slot"), Channel.MaterialSlot) ||
					Channel.MaterialSlot < 0 || Channel.MaterialSlot >= Part.Mesh->GetStaticMaterials().Num()) return false;
				UMaterialInterface* Material = Part.Materials.Contains(Channel.MaterialSlot) ? Part.Materials[Channel.MaterialSlot] : Part.Mesh->GetMaterial(Channel.MaterialSlot);
				if (!Material->GetScalarParameterValue(FMaterialParameterInfo(FName(*Parameter)), Channel.Motion.ReadyScalar)) return false;
				Channel.Motion.ScalarParameter = FName(*Parameter);
			}
			if (!(*Object)->TryGetArrayField(TEXT("keyframes"), Frames) || Frames->Num() < 2 || Frames->Num() > 128) return false;
			bool bChangesVisiblePart = false;
			for (const auto& FrameValue : *Frames)
			{
				const TSharedPtr<FJsonObject>* FrameObject = nullptr;
				FCWEraMotionFrame Frame;
				FVector Rotation = FVector::ZeroVector;
				double Time, Scalar = Channel.Motion.ReadyScalar;
				if (!FrameValue->TryGetObject(FrameObject) || !(*FrameObject)->TryGetNumberField(TEXT("time"), Time) ||
					!FMath::IsFinite(Time) || Time < 0. || Time > Duration + 0.0001 ||
					(!Channel.Motion.Frames.IsEmpty() && Time <= Channel.Motion.Frames.Last().Time) ||
					!VectorField(*FrameObject, TEXT("translation_cm"), Frame.Translation) ||
					!VectorField(*FrameObject, TEXT("rotation_degrees"), Rotation)) return false;
				if ((*FrameObject)->HasField(TEXT("scalar")) && (!(*FrameObject)->TryGetNumberField(TEXT("scalar"), Scalar) ||
					Channel.Motion.ScalarParameter.IsNone())) return false;
				if (!FMath::IsFinite(Scalar)) return false;
				if ((*FrameObject)->HasField(TEXT("visible")) && !(*FrameObject)->TryGetBoolField(TEXT("visible"), Frame.bVisible)) return false;
				Frame.Time = static_cast<float>(Time);
				Frame.Rotation = FRotator(Rotation.X, Rotation.Y, Rotation.Z);
				Frame.Scalar = static_cast<float>(Scalar);
				bChangesVisiblePart |= !Frame.Translation.IsNearlyZero() || !Frame.Rotation.IsNearlyZero() ||
					!Frame.bVisible || !FMath::IsNearlyEqual(Frame.Scalar, Channel.Motion.ReadyScalar);
				Channel.Motion.Frames.Add(Frame);
			}
			const FCWEraMotionFrame& Last = Channel.Motion.Frames.Last();
			if (!bChangesVisiblePart || Channel.Motion.Frames[0].Time != 0.f || !FMath::IsNearlyEqual(Last.Time, Duration, 0.001f) ||
				!Last.Translation.IsNearlyZero() || !Last.Rotation.IsNearlyZero() || !Last.bVisible ||
				!FMath::IsNearlyEqual(Last.Scalar, Channel.Motion.ReadyScalar)) return false;
			Channels.Add(MoveTemp(Channel));
		}
		return true;
	}

	void ApplyFirePose(FCWTurretRig& Rig)
	{
		for (FCWEraMotionChannel& Channel : Rig.EraChannels)
		{
			const FCWEraMotionFrame Pose = CWEraArt::SampleMotion(Channel.Frames, Rig.EraFireElapsed);
			FTransform Transform = Channel.ReadyTransform;
			Transform.AddToTranslation(Pose.Translation);
			Transform.SetRotation(Channel.ReadyTransform.GetRotation() * Pose.Rotation.Quaternion());
			Channel.Component->SetRelativeTransform(Transform);
			Channel.Component->SetVisibility(Pose.bVisible, true);
			if (Channel.Material) Channel.Material->SetScalarParameterValue(Channel.ScalarParameter, Pose.Scalar);
		}
	}

	void SampleCrew(FCWTurretRig& Rig, float Dt, bool bRestart = false)
	{
		const bool bFiring = Rig.EraFireElapsed >= 0.f;
		for (FCWEraSkeletalPart& Part : Rig.EraSkeletalParts)
		{
			UAnimSequence* Clip = bFiring ? Part.FireClip.Get() : Part.ReadyClip.Get();
			const bool bChanged = Clip != Part.SampledClip;
			const float Time = bFiring ? FMath::Min(Rig.EraFireElapsed, Clip->GetPlayLength()) :
				FMath::Fmod(Rig.EraReadyElapsed, Clip->GetPlayLength());
			auto* Instance = CastChecked<UCWSmoothUnitAnimInstance>(Part.Component->GetSingleNodeInstance());
			// Fire t=0 is already the authoritative release. Never blend it away.
			Instance->PrepareBlend(bChanged || bRestart, bFiring || !Part.SampledClip ? 0.f : 0.08f, Dt);
			if (bChanged) Part.Component->SetAnimation(Clip);
			Part.Component->SetPosition(Time, false);
			Part.Component->TickAnimation(0.f, false);
			Part.Component->RefreshBoneTransforms();
			Part.Component->UpdateComponentToWorld();
			Part.SampledClip = Clip;
		}
	}
}

const cw::UnitDef* CWEraArt::FindUnit(AActor* Owner, FName VisualKey)
{
	if (const cw::GameData* Data = DataFor(Owner))
		for (const cw::UnitDef& Def : Data->Units)
			if (FName(UTF8_TO_TCHAR(Def.VisualKey.c_str())) == VisualKey) return &Def;
	return nullptr;
}

TSharedPtr<FJsonObject> CWEraArt::LoadEntry(FName VisualKey, const TCHAR* Kind)
{
	if (FParse::Param(FCommandLine::Get(), TEXT("cwlegacyart"))) return nullptr;
	FString Text, AssetId, EntryKind;
	TSharedPtr<FJsonObject> Root;
	const TSharedPtr<FJsonObject>* Assets = nullptr;
	const TSharedPtr<FJsonObject>* Entry = nullptr;
	if (!FFileHelper::LoadFileToString(Text, *(FPaths::ProjectContentDir() / TEXT("Data/EraArt.json"))) ||
		!FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text), Root) || !Root ||
		!Root->TryGetObjectField(TEXT("assets"), Assets) || !(*Assets)->TryGetObjectField(VisualKey.ToString(), Entry) ||
		!(*Entry)->TryGetStringField(TEXT("asset_id"), AssetId) || AssetId != VisualKey.ToString() ||
		!(*Entry)->TryGetStringField(TEXT("kind"), EntryKind) || EntryKind != Kind || !Flag(*Entry, TEXT("enabled"))) return nullptr;
	if (!Flag(*Entry, TEXT("default_runtime_enabled")) &&
		!(FParse::Param(FCommandLine::Get(), TEXT("cwerapreview")) && Flag(*Entry, TEXT("preview_enabled")))) return nullptr;
	return *Entry;
}

bool CWEraArt::TryBuildBase(AActor* Owner, USceneComponent* Parent, int32 Age, int32 Team, FCWBaseRig& Rig)
{
	const cw::GameData* Data = DataFor(Owner);
	if (!Data || !Parent || Age <= 0 || Age >= static_cast<int32>(Data->Ages.size())) return false;
	const FName Key(UTF8_TO_TCHAR(Data->Ages[Age].VisualKey.c_str()));
	const TSharedPtr<FJsonObject> Config = LoadEntry(Key, TEXT("static_base"));
	if (!Config) return false;
	TArray<FPart> Parts;
	FBox Bounds(ForceInit);
	const TSharedPtr<FJsonObject>* Anchors = nullptr;
	if (!ReadParts(Config, Team, Parts, Bounds) || !Config->TryGetObjectField(TEXT("anchors_cm"), Anchors)) return false;
	TArray<FVector> Mounts;
	for (int32 Slot = 0; Slot < 3; ++Slot)
	{
		FVector Position;
		if (!VectorValue((*Anchors)->TryGetField(FString::Printf(TEXT("turret_%d"), Slot)), Position) ||
			!Bounds.ExpandBy(1.f).IsInsideOrOn(Position) || Position.Z <= 0.) return false;
		Mounts.Add(Position);
	}
	FVector Gate = FVector::ZeroVector;
	const bool bHasGate = (*Anchors)->HasField(TEXT("gate"));
	if (bHasGate && !VectorValue((*Anchors)->TryGetField(TEXT("gate")), Gate)) return false;
	BuildParts(Owner, Parent, Parts, Team);
	Rig.TurretMounts = MoveTemp(Mounts);
	Rig.Height = Bounds.Max.Z;
	Rig.bHasMeasuredGate = bHasGate;
	Rig.MeasuredGate = Gate;
	UE_LOG(LogTemp, Display, TEXT("CIVWAR_ERA_ART kind=static_base asset=%s team=%d parts=%d mounts=3"), *Key.ToString(), Team, Parts.Num());
	return true;
}

bool CWEraArt::TryBuildTurret(AActor* Owner, USceneComponent* Parent, FName VisualKey, int32 Team, FCWTurretRig& Rig)
{
	const cw::GameData* Data = DataFor(Owner);
	if (!Data || !Parent) return false;
	const cw::TurretDef* Definition = nullptr;
	for (const cw::TurretDef& Def : Data->Turrets)
		if (FName(UTF8_TO_TCHAR(Def.VisualKey.c_str())) == VisualKey) { Definition = &Def; break; }
	if (!Definition || Definition->Age == 0) return false;
	const TSharedPtr<FJsonObject> Config = LoadEntry(VisualKey, TEXT("mechanical_turret"));
	if (!Config) return false;
	TArray<FPart> Parts;
	TArray<FChannel> Channels;
	TArray<FSkeletalPart> SkeletalParts;
	FBox Bounds(ForceInit);
	const TSharedPtr<FJsonObject>* Fire = nullptr;
	const TSharedPtr<FJsonObject>* Muzzle = nullptr;
	FString MuzzlePart, MuzzleSocket;
	FTransform MuzzleTransform;
	double Duration;
	if (!ReadParts(Config, Team, Parts, Bounds) || !Config->TryGetObjectField(TEXT("fire_animation"), Fire) ||
		!(*Fire)->TryGetNumberField(TEXT("duration"), Duration) || !FMath::IsFinite(Duration) || Duration <= 0. || Duration > Definition->AttackInterval + 0.0001 ||
		!ReadChannels(*Fire, Parts, static_cast<float>(Duration), Channels) ||
		!ReadSkeletalParts(Config, Parts, Team, static_cast<float>(Duration), SkeletalParts) ||
		(Channels.IsEmpty() && SkeletalParts.IsEmpty()) || !Config->TryGetObjectField(TEXT("muzzle"), Muzzle) ||
		!(*Muzzle)->TryGetStringField(TEXT("part"), MuzzlePart) ||
		!ReadTransform(*Muzzle, MuzzleTransform)) return false;
	const int32 MuzzleIndex = PartIndex(Parts, MuzzlePart);
	const int32 SkeletalMuzzle = SkeletalParts.IndexOfByPredicate([&](const FSkeletalPart& Part) { return Part.Id == MuzzlePart; });
	if (SkeletalMuzzle != INDEX_NONE)
	{
		if (!(*Muzzle)->TryGetStringField(TEXT("socket"), MuzzleSocket) || MuzzleSocket.IsEmpty()) return false;
		const USkeletalMesh* Mesh = SkeletalParts[SkeletalMuzzle].Mesh;
		if (Mesh->GetRefSkeleton().FindBoneIndex(FName(*MuzzleSocket)) == INDEX_NONE &&
			!Mesh->FindSocket(FName(*MuzzleSocket))) return false;
	}
	else if (MuzzleIndex == INDEX_NONE || !MovesMesh(Parts, MuzzleIndex) || !(*Muzzle)->HasField(TEXT("translation_cm"))) return false;
	Rig.Root = CWVisual::AddPivot(Owner, Parent, FVector::ZeroVector);
	const TArray<USceneComponent*> Components = BuildParts(Owner, Rig.Root, Parts, Team);
	for (const FSkeletalPart& Source : SkeletalParts)
	{
		auto* Component = NewObject<USkeletalMeshComponent>(Owner);
		Owner->AddInstanceComponent(Component);
		Component->SetupAttachment(Components[Source.Parent]);
		Component->SetRelativeTransform(Source.Transform);
		Component->SetSkeletalMesh(Source.Mesh);
		Component->SetAnimInstanceClass(UCWSmoothUnitAnimInstance::StaticClass());
		Component->VisibilityBasedAnimTickOption = EVisibilityBasedAnimTickOption::AlwaysTickPoseAndRefreshBones;
		Component->bEnableUpdateRateOptimizations = false;
		Component->SetCollisionEnabled(ECollisionEnabled::NoCollision);
		Component->SetGenerateOverlapEvents(false);
		Component->bSuppressNotifyEventDispatch = true;
		Component->RegisterComponent();
		Component->SetComponentTickEnabled(false);
		for (const auto& Material : Source.Materials)
		{
			auto* Instance = Component->CreateDynamicMaterialInstance(Material.Key, Material.Value);
			Instance->SetVectorParameterValue(TEXT("TeamColor"), CWVisual::TeamColor(Team));
			Instance->SetScalarParameterValue(TEXT("TeamColorStrength"), 1.f);
		}
		FCWEraSkeletalPart Part;
		Part.Component = Component;
		Part.ReadyClip.Reset(Source.Ready);
		Part.FireClip.Reset(Source.Fire);
		Rig.EraSkeletalParts.Add(MoveTemp(Part));
	}
	USceneComponent* MuzzleParent = SkeletalMuzzle == INDEX_NONE ? Components[MuzzleIndex] : Rig.EraSkeletalParts[SkeletalMuzzle].Component;
	Rig.Muzzle = NewObject<USceneComponent>(Owner);
	Owner->AddInstanceComponent(Rig.Muzzle);
	Rig.Muzzle->SetupAttachment(MuzzleParent, FName(*MuzzleSocket));
	Rig.Muzzle->SetRelativeTransform(MuzzleTransform);
	Rig.Muzzle->RegisterComponent();
	for (FChannel& Source : Channels)
	{
		Source.Motion.Component = Components[Source.Part];
		Source.Motion.ReadyTransform = Parts[Source.Part].Transform;
		if (Source.MaterialSlot != INDEX_NONE)
			Source.Motion.Material = CastChecked<UStaticMeshComponent>(Components[Source.Part])->CreateDynamicMaterialInstance(Source.MaterialSlot);
		Rig.EraChannels.Add(MoveTemp(Source.Motion));
	}
	Rig.bEraArt = true;
	Rig.EraFireDuration = static_cast<float>(Duration);
	SampleCrew(Rig, 0.f);
	UE_LOG(LogTemp, Display, TEXT("CIVWAR_ERA_ART kind=mechanical_turret asset=%s team=%d parts=%d channels=%d crew=%d source=authoritative_fireseq"), *VisualKey.ToString(), Team, Parts.Num(), Rig.EraChannels.Num(), Rig.EraSkeletalParts.Num());
	return true;
}

FCWEraMotionFrame CWEraArt::SampleMotion(const TArray<FCWEraMotionFrame>& Frames, float Time)
{
	if (Frames.IsEmpty()) return FCWEraMotionFrame();
	if (Time <= Frames[0].Time) return Frames[0];
	for (int32 Index = 1; Index < Frames.Num(); ++Index)
	{
		const FCWEraMotionFrame& A = Frames[Index - 1];
		const FCWEraMotionFrame& B = Frames[Index];
		if (Time < B.Time)
		{
			const float T = FMath::Clamp((Time - A.Time) / (B.Time - A.Time), 0.f, 1.f);
			const float Alpha = T * T * (3.f - 2.f * T);
			FCWEraMotionFrame Result = A;
			Result.Translation = FMath::Lerp(A.Translation, B.Translation, Alpha);
			Result.Rotation = FQuat::Slerp(A.Rotation.Quaternion(), B.Rotation.Quaternion(), Alpha).Rotator();
			Result.Scalar = FMath::Lerp(A.Scalar, B.Scalar, Alpha);
			return Result;
		}
	}
	return Frames.Last();
}

void CWEraArt::BeginFire(FCWTurretRig& Rig)
{
	if (!Rig.bEraArt) return;
	Rig.EraFireElapsed = 0.f;
	ApplyFirePose(Rig); // Server release already happened; never start a new windup.
	SampleCrew(Rig, 0.f, true);
}

bool CWEraArt::UpdateTurret(FCWTurretRig& Rig, float Dt)
{
	if (!Rig.bEraArt) return false;
	if (Rig.EraFireElapsed >= 0.f && FMath::IsFinite(Dt) && Dt > 0.f)
	{
		Rig.EraFireElapsed = FMath::Min(Rig.EraFireDuration, Rig.EraFireElapsed + Dt);
		ApplyFirePose(Rig);
		if (Rig.EraFireElapsed >= Rig.EraFireDuration)
		{
			Rig.EraFireElapsed = -1.f;
			Rig.EraReadyElapsed = 0.f;
		}
	}
	else if (FMath::IsFinite(Dt) && Dt > 0.f) Rig.EraReadyElapsed += Dt;
	SampleCrew(Rig, FMath::IsFinite(Dt) ? FMath::Max(0.f, Dt) : 0.f);
	return true;
}
