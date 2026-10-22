// 极简 JSON 解析器：仅供独立测试程序读取 Content/Data/*.json（游戏内由 UE DataTable 读取同一份文件）
#pragma once

#include <cstdint>
#include <cstdlib>
#include <string>
#include <vector>

namespace mj
{
	enum class Type { Null, Bool, Number, String, Array, Object };

	struct Value
	{
		Type T = Type::Null;
		bool B = false;
		double N = 0.0;
		std::string S;
		std::vector<Value> Items;          // Array
		std::vector<std::string> Keys;     // Object
		std::vector<Value> Vals;           // Object

		const Value* Get(const std::string& Key) const
		{
			for (size_t I = 0; I < Keys.size(); ++I)
			{
				if (Keys[I] == Key)
				{
					return &Vals[I];
				}
			}
			return nullptr;
		}
	};

	class Parser
	{
	public:
		explicit Parser(const std::string& InText) : Text(InText) {}

		bool Parse(Value& Out, std::string& Error)
		{
			SkipWs();
			if (!ParseValue(Out))
			{
				Error = Err.empty() ? "parse error" : Err;
				Error += " at offset " + std::to_string(Pos);
				return false;
			}
			SkipWs();
			if (Pos != Text.size())
			{
				Error = "trailing characters at offset " + std::to_string(Pos);
				return false;
			}
			return true;
		}

	private:
		const std::string& Text;
		size_t Pos = 0;
		std::string Err;

		void SkipWs()
		{
			while (Pos < Text.size() && (Text[Pos] == ' ' || Text[Pos] == '\t' || Text[Pos] == '\n' || Text[Pos] == '\r'))
			{
				++Pos;
			}
		}

		bool Match(const char* Lit)
		{
			size_t I = 0;
			while (Lit[I] != '\0')
			{
				if (Pos + I >= Text.size() || Text[Pos + I] != Lit[I])
				{
					return false;
				}
				++I;
			}
			Pos += I;
			return true;
		}

		bool ParseValue(Value& Out)
		{
			if (Pos >= Text.size())
			{
				Err = "unexpected end";
				return false;
			}
			const char C = Text[Pos];
			if (C == '{') return ParseObject(Out);
			if (C == '[') return ParseArray(Out);
			if (C == '"') { Out.T = Type::String; return ParseString(Out.S); }
			if (Match("true")) { Out.T = Type::Bool; Out.B = true; return true; }
			if (Match("false")) { Out.T = Type::Bool; Out.B = false; return true; }
			if (Match("null")) { Out.T = Type::Null; return true; }
			return ParseNumber(Out);
		}

		bool ParseNumber(Value& Out)
		{
			const char* Begin = Text.c_str() + Pos;
			char* End = nullptr;
			const double V = std::strtod(Begin, &End);
			if (End == Begin)
			{
				Err = "invalid token";
				return false;
			}
			Pos += static_cast<size_t>(End - Begin);
			Out.T = Type::Number;
			Out.N = V;
			return true;
		}

		static void AppendUtf8(std::string& S, uint32_t Cp)
		{
			if (Cp < 0x80)
			{
				S.push_back(static_cast<char>(Cp));
			}
			else if (Cp < 0x800)
			{
				S.push_back(static_cast<char>(0xC0 | (Cp >> 6)));
				S.push_back(static_cast<char>(0x80 | (Cp & 0x3F)));
			}
			else if (Cp < 0x10000)
			{
				S.push_back(static_cast<char>(0xE0 | (Cp >> 12)));
				S.push_back(static_cast<char>(0x80 | ((Cp >> 6) & 0x3F)));
				S.push_back(static_cast<char>(0x80 | (Cp & 0x3F)));
			}
			else
			{
				S.push_back(static_cast<char>(0xF0 | (Cp >> 18)));
				S.push_back(static_cast<char>(0x80 | ((Cp >> 12) & 0x3F)));
				S.push_back(static_cast<char>(0x80 | ((Cp >> 6) & 0x3F)));
				S.push_back(static_cast<char>(0x80 | (Cp & 0x3F)));
			}
		}

		bool ParseHex4(uint32_t& Out)
		{
			if (Pos + 4 > Text.size())
			{
				return false;
			}
			Out = 0;
			for (int I = 0; I < 4; ++I)
			{
				const char H = Text[Pos++];
				Out <<= 4;
				if (H >= '0' && H <= '9') Out |= static_cast<uint32_t>(H - '0');
				else if (H >= 'a' && H <= 'f') Out |= static_cast<uint32_t>(H - 'a' + 10);
				else if (H >= 'A' && H <= 'F') Out |= static_cast<uint32_t>(H - 'A' + 10);
				else return false;
			}
			return true;
		}

		bool ParseString(std::string& Out)
		{
			++Pos; // "
			Out.clear();
			while (Pos < Text.size())
			{
				const char C = Text[Pos++];
				if (C == '"')
				{
					return true;
				}
				if (C != '\\')
				{
					Out.push_back(C);
					continue;
				}
				if (Pos >= Text.size())
				{
					break;
				}
				const char Esc = Text[Pos++];
				switch (Esc)
				{
				case '"': Out.push_back('"'); break;
				case '\\': Out.push_back('\\'); break;
				case '/': Out.push_back('/'); break;
				case 'b': Out.push_back('\b'); break;
				case 'f': Out.push_back('\f'); break;
				case 'n': Out.push_back('\n'); break;
				case 'r': Out.push_back('\r'); break;
				case 't': Out.push_back('\t'); break;
				case 'u':
				{
					uint32_t Cp = 0;
					if (!ParseHex4(Cp))
					{
						Err = "bad \\u escape";
						return false;
					}
					if (Cp >= 0xD800 && Cp <= 0xDBFF && Pos + 6 <= Text.size() && Text[Pos] == '\\' && Text[Pos + 1] == 'u')
					{
						Pos += 2;
						uint32_t Lo = 0;
						if (!ParseHex4(Lo))
						{
							Err = "bad surrogate";
							return false;
						}
						Cp = 0x10000 + ((Cp - 0xD800) << 10) + (Lo - 0xDC00);
					}
					AppendUtf8(Out, Cp);
					break;
				}
				default:
					Err = "bad escape";
					return false;
				}
			}
			Err = "unterminated string";
			return false;
		}

		bool ParseArray(Value& Out)
		{
			Out.T = Type::Array;
			++Pos; // [
			SkipWs();
			if (Pos < Text.size() && Text[Pos] == ']')
			{
				++Pos;
				return true;
			}
			while (true)
			{
				Value Item;
				SkipWs();
				if (!ParseValue(Item))
				{
					return false;
				}
				Out.Items.push_back(Item);
				SkipWs();
				if (Pos < Text.size() && Text[Pos] == ',')
				{
					++Pos;
					continue;
				}
				if (Pos < Text.size() && Text[Pos] == ']')
				{
					++Pos;
					return true;
				}
				Err = "expected , or ]";
				return false;
			}
		}

		bool ParseObject(Value& Out)
		{
			Out.T = Type::Object;
			++Pos; // {
			SkipWs();
			if (Pos < Text.size() && Text[Pos] == '}')
			{
				++Pos;
				return true;
			}
			while (true)
			{
				SkipWs();
				if (Pos >= Text.size() || Text[Pos] != '"')
				{
					Err = "expected key";
					return false;
				}
				std::string Key;
				if (!ParseString(Key))
				{
					return false;
				}
				SkipWs();
				if (Pos >= Text.size() || Text[Pos] != ':')
				{
					Err = "expected :";
					return false;
				}
				++Pos;
				SkipWs();
				Value Val;
				if (!ParseValue(Val))
				{
					return false;
				}
				Out.Keys.push_back(Key);
				Out.Vals.push_back(Val);
				SkipWs();
				if (Pos < Text.size() && Text[Pos] == ',')
				{
					++Pos;
					continue;
				}
				if (Pos < Text.size() && Text[Pos] == '}')
				{
					++Pos;
					return true;
				}
				Err = "expected , or }";
				return false;
			}
		}
	};
}
