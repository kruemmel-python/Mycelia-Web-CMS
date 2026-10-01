#pragma once
#include <string>
#include <vector>
namespace mycelia {
enum class Op {
    Spawn, Link, Mutate, EraseNode, Get, Trace, Pulse, ListNodes, ListLinks, GpuStatus,
    Ping, ImportText, ImportSql, ListDocs, Search, GetDoc,
    IngestText, IngestSql, IngestOcrImage, OcrStatus, QueryField, ExplainResonance, GetNeighbors, FieldStatus, SaveDb, LoadDb, ClearDb, GetMediaForNode, GetMediaForSegment, GetImageInfo,
    Help, Unknown
};
struct Command { Op op{Op::Unknown}; std::vector<std::string> args; };
Command parse_command(const std::string& line);
std::string op_name(Op op);
std::string trim(const std::string& s);
}