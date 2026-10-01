#include "common/Protocol.hpp"
#include <algorithm>
#include <cctype>
namespace mycelia {
std::string trim(const std::string& s){auto b=s.find_first_not_of(" \t\r\n"); if(b==std::string::npos)return{}; auto e=s.find_last_not_of(" \t\r\n"); return s.substr(b,e-b+1);}
static std::string upper(std::string s){std::transform(s.begin(),s.end(),s.begin(),[](unsigned char c){return (char)std::toupper(c);}); return s;}
static std::vector<std::string> tokenize(const std::string& line){
    std::vector<std::string> out; std::string cur; bool q=false, esc=false; char qc=0;
    for(char ch: line){ if(esc){cur.push_back(ch); esc=false; continue;} if(ch=='\\'&&q){esc=true; continue;}
        if((ch=='"'||ch=='\'')&&!q){q=true; qc=ch; continue;} if(q&&ch==qc){q=false; continue;}
        if(!q && std::isspace((unsigned char)ch)){ if(!cur.empty()){out.push_back(cur); cur.clear();} continue; }
        cur.push_back(ch);
    } if(!cur.empty()) out.push_back(cur); return out;
}
Command parse_command(const std::string& line){ auto toks=tokenize(line); Command c; if(toks.empty()) return c; auto tok=upper(toks.front());
    if(tok=="SPAWN") c.op=Op::Spawn; else if(tok=="LINK") c.op=Op::Link; else if(tok=="MUTATE") c.op=Op::Mutate; else if(tok=="ERASE_NODE") c.op=Op::EraseNode;
    else if(tok=="GET") c.op=Op::Get; else if(tok=="TRACE") c.op=Op::Trace; else if(tok=="PULSE") c.op=Op::Pulse;
    else if(tok=="LIST_NODES") c.op=Op::ListNodes; else if(tok=="LIST_LINKS") c.op=Op::ListLinks; else if(tok=="GPU_STATUS") c.op=Op::GpuStatus;
    else if(tok=="PING") c.op=Op::Ping; else if(tok=="IMPORT_TEXT") c.op=Op::ImportText; else if(tok=="IMPORT_SQL") c.op=Op::ImportSql;
    else if(tok=="INGEST_TEXT") c.op=Op::IngestText; else if(tok=="INGEST_SQL"||tok=="INGEST_SQL_DUMP") c.op=Op::IngestSql;
    else if(tok=="INGEST_OCR_IMAGE"||tok=="IMPORT_IMAGE"||tok=="OCR_IMAGE"||tok=="INGEST_IMAGE") c.op=Op::IngestOcrImage;
    else if(tok=="OCR_STATUS") c.op=Op::OcrStatus;
    else if(tok=="LIST_DOCS") c.op=Op::ListDocs; else if(tok=="SEARCH") c.op=Op::Search; else if(tok=="QUERY_FIELD"||tok=="QUERY") c.op=Op::QueryField;
    else if(tok=="EXPLAIN_RESONANCE"||tok=="EXPLAIN") c.op=Op::ExplainResonance; else if(tok=="GET_DOC") c.op=Op::GetDoc;
    else if(tok=="GET_NEIGHBORS"||tok=="NEIGHBORS") c.op=Op::GetNeighbors; else if(tok=="FIELD_STATUS") c.op=Op::FieldStatus;
    else if(tok=="SAVE_DB"||tok=="SAVE"||tok=="CHECKPOINT") c.op=Op::SaveDb;
    else if(tok=="LOAD_DB"||tok=="LOAD"||tok=="RESTORE") c.op=Op::LoadDb;
    else if(tok=="CLEAR_DB"||tok=="NEW_DB") c.op=Op::ClearDb;
    else if(tok=="GET_MEDIA_FOR_NODE") c.op=Op::GetMediaForNode;
    else if(tok=="GET_MEDIA_FOR_SEGMENT") c.op=Op::GetMediaForSegment;
    else if(tok=="GET_IMAGE_INFO") c.op=Op::GetImageInfo;
    else if(tok=="HELP") c.op=Op::Help;
    for(size_t i=1;i<toks.size();++i) {
        c.args.push_back(toks[i]);
    }
    return c;
}
std::string op_name(Op op){switch(op){case Op::QueryField:return"QUERY_FIELD";case Op::ExplainResonance:return"EXPLAIN_RESONANCE";case Op::IngestText:return"INGEST_TEXT";case Op::IngestSql:return"INGEST_SQL";case Op::IngestOcrImage:return"INGEST_OCR_IMAGE";case Op::OcrStatus:return"OCR_STATUS";default:return"MYCELIA";}}
}