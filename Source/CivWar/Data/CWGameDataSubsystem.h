// 血战文明 - 数据加载子系统：Content/Data/*.json → UDataTable → cw::GameData
#pragma once

#include "CoreMinimal.h"
#include "Subsystems/GameInstanceSubsystem.h"
#include "Sim/SimTypes.h"
#include "CWGameDataSubsystem.generated.h"

class UDataTable;

UCLASS()
class CIVWAR_API UCWGameDataSubsystem : public UGameInstanceSubsystem
{
	GENERATED_BODY()

public:
	virtual void Initialize(FSubsystemCollectionBase& Collection) override;

	bool IsLoaded() const { return bLoaded; }
	const FString& GetLoadError() const { return LoadError; }
	const cw::GameData& GetData() const { return Data; }

	// 所有数据文件内容的校验值；联机时服务器下发，客户端不一致则拒绝进入对局
	uint32 GetChecksum() const { return Checksum; }

	// 界面文本（中文）
	FText GetUnitName(int32 UnitIndex) const;
	FText GetUnitDescription(int32 UnitIndex) const;
	FText GetAgeName(int32 AgeIndex) const;
	FText GetTurretName(int32 TurretIndex) const;
	FText GetTurretDescription(int32 TurretIndex) const;
	FText GetSkillName(int32 SkillIndex) const;
	FText GetSkillDescription(int32 SkillIndex) const;
	FName GetUnitVisualKey(int32 UnitIndex) const;
	FName GetTurretVisualKey(int32 TurretIndex) const;
	// 统帅（Champions 下标）与国策（Doctrines 下标）
	FText GetChampionName(int32 ChampionIndex) const;
	FText GetChampionDescription(int32 ChampionIndex) const;
	FText GetChampionAbilityName(int32 ChampionIndex) const;
	FText GetChampionAbilityDescription(int32 ChampionIndex) const;
	FText GetDoctrineName(int32 DoctrineIndex) const;
	FText GetDoctrineDescription(int32 DoctrineIndex) const;
	FText GetDoctrineCategory(int32 DoctrineIndex) const;

	UDataTable* GetUnitTable() const { return UnitTable; }

	static FString GetDataDirectory();

private:
	bool LoadAll(FString& OutError);
	UDataTable* LoadTable(const FString& FileName, UScriptStruct* RowStruct, FString& OutError);

	UPROPERTY(Transient)
	TObjectPtr<UDataTable> RulesTable;
	UPROPERTY(Transient)
	TObjectPtr<UDataTable> MatrixTable;
	UPROPERTY(Transient)
	TObjectPtr<UDataTable> AgeTable;
	UPROPERTY(Transient)
	TObjectPtr<UDataTable> UnitTable;
	UPROPERTY(Transient)
	TObjectPtr<UDataTable> TurretTable;
	UPROPERTY(Transient)
	TObjectPtr<UDataTable> SkillTable;
	UPROPERTY(Transient)
	TObjectPtr<UDataTable> ChampionTable;
	UPROPERTY(Transient)
	TObjectPtr<UDataTable> DoctrineTable;

	TArray<FString> UnitDescriptions;
	TArray<FString> TurretDescriptions;
	TArray<FString> SkillDescriptions;
	TArray<FName> UnitVisualKeys;
	TArray<FName> TurretVisualKeys;
	TArray<FString> ChampionDescriptions;
	TArray<FString> ChampionAbilityNames;
	TArray<FString> ChampionAbilityDescriptions;
	TArray<FString> DoctrineDescriptions;
	TArray<FString> DoctrineCategories;

	cw::GameData Data;
	bool bLoaded = false;
	FString LoadError;
	uint32 Checksum = 0;
};
