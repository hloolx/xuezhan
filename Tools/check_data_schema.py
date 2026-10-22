# -*- coding: utf-8 -*-
"""
Verify that Content/Data/*.json matches the DataTable row structs in Source/CivWar/Data/CWDataTypes.h.

UE's DataTable JSON importer reports a problem for every struct field that has no JSON entry, and the game
refuses to start a match when the data fails to load - so field names and enum values must stay in sync.

Usage: python Tools/check_data_schema.py   (exit code 0 = OK)
"""
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TABLES = {
    "Rules": "FCWRulesRow",
    "DamageMatrix": "FCWDamageMatrixRow",
    "Ages": "FCWAgeRow",
    "Units": "FCWUnitRow",
    "Turrets": "FCWTurretRow",
    "Skills": "FCWSkillRow",
    "Champions": "FCWChampionRow",
    "Doctrines": "FCWDoctrineRow",
}


def main():
    src = io.open(os.path.join(ROOT, "Source", "CivWar", "Data", "CWDataTypes.h"), encoding="utf-8").read()
    structs = {}
    enum_fields = {}
    for name, body in re.findall(r"struct (FCW\w+Row) : public FTableRowBase\s*\{(.*?)\n\};", src, re.S):
        structs[name] = re.findall(r"UPROPERTY\([^)]*\)\s*[\w:<>]+\s+(\w+)\s*(?:=|;)", body)
        for enum_type, field in re.findall(r"UPROPERTY\([^)]*\)\s*(ECW\w+)\s+(\w+)", body):
            enum_fields[(name, field)] = enum_type
    enums = {}
    for name, body in re.findall(r"enum class (ECW\w+) : uint8\s*\{(.*?)\};", src, re.S):
        enums[name] = [v.strip() for v in body.replace("\n", "").split(",") if v.strip()]

    errors = 0
    for table, struct in TABLES.items():
        path = os.path.join(ROOT, "Content", "Data", table + ".json")
        rows = json.load(io.open(path, encoding="utf-8"))
        fields = structs.get(struct, [])
        names = set()
        for row in rows:
            row_name = row.get("Name")
            if not row_name or row_name in names:
                print("[%s] missing or duplicate row Name: %r" % (table, row_name))
                errors += 1
            names.add(row_name)
            missing = [f for f in fields if f not in row]
            extra = sorted(set(row) - set(fields) - {"Name"})
            bad_enum = [(f, row[f]) for f in fields if (struct, f) in enum_fields and row.get(f) not in enums[enum_fields[(struct, f)]]]
            for label, items in (("missing fields", missing), ("unknown fields", extra), ("invalid enum values", bad_enum)):
                if items:
                    print("[%s] row %s: %s %s" % (table, row_name, label, items))
                    errors += 1
        print("%-13s %-20s rows=%d fields=%d" % (table, struct, len(rows), len(fields)))
    print("schema OK" if errors == 0 else "schema errors: %d" % errors)
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
