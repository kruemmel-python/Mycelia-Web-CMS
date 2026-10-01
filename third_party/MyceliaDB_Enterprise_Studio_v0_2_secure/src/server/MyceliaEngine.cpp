#include "server/MyceliaEngine.hpp"
#include <algorithm>
#include <cctype>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <queue>
#include <sstream>
#include <map>
#include <cstdio>
#include <cstdlib>
#include <chrono>
#include <regex>
#include <ctime>
#include <cwctype>
#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#endif

namespace fs=std::filesystem;
namespace mycelia {
namespace {
std::string low(std::string s){std::transform(s.begin(),s.end(),s.begin(),[](unsigned char c){return(char)std::tolower(c);}); return s;}
std::string canonical_label(std::string s){
    s=low(s);
    for(char& c:s){
        unsigned char u=(unsigned char)c;
        if(!(std::isalnum(u)||u>=128)) c=' ';
    }
    s=std::regex_replace(s,std::regex("\\s+")," ");
    return s;
}
std::string sanitize(std::string s){for(char& c:s) if(!(std::isalnum((unsigned char)c)||c=='_'||c=='-'||c=='.'||c==':')) c='_'; if(s.empty())s="cell"; return s;}
std::string node_id(const std::string&p,const std::string&l){return p+":"+sanitize(low(l));}
std::string read_file(const std::string&p){std::ifstream in(p,std::ios::binary); if(!in)return{}; std::ostringstream ss; ss<<in.rdbuf(); return ss.str();}

std::string file_ext_lower(const std::string& p){
    auto e=low(fs::path(p).extension().string());
    if(!e.empty() && e[0]=='.') e=e.substr(1);
    return e.empty()?"bin":e;
}
std::string mime_for_path(const std::string& p){
    auto e=file_ext_lower(p);
    if(e=="png") return "image/png";
    if(e=="jpg"||e=="jpeg") return "image/jpeg";
    if(e=="tif"||e=="tiff") return "image/tiff";
    if(e=="bmp") return "image/bmp";
    if(e=="webp") return "image/webp";
    return "application/octet-stream";
}
std::string weak_hash_file(const std::string& p){
    std::ifstream in(p,std::ios::binary);
    uint64_t h=1469598103934665603ULL;
    char c;
    while(in.get(c)){ h^=(unsigned char)c; h*=1099511628211ULL; }
    std::ostringstream o; o<<std::hex<<h; return o.str();
}
std::string trim2(const std::string&s){auto b=s.find_first_not_of(" \t\r\n"); if(b==std::string::npos)return{}; auto e=s.find_last_not_of(" \t\r\n"); return s.substr(b,e-b+1);}
bool snapshot_path_allowed(const std::string& raw){
    const char* rootEnv = std::getenv("MYCELIA_DB_STORAGE_ROOT");
    if(!rootEnv || !*rootEnv) return false;
    fs::path target = fs::absolute(fs::path(raw)).lexically_normal();
    fs::path root = fs::absolute(fs::path(rootEnv)).lexically_normal();
    if(low(target.extension().string()) != ".mycdb") return false;
#ifdef _WIN32
    auto lower_path=[](fs::path p){
        std::wstring w=p.wstring();
        std::transform(w.begin(),w.end(),w.begin(),[](wchar_t c){return (wchar_t)std::towlower(c);});
        return fs::path(w);
    };
    target=lower_path(target);
    root=lower_path(root);
#endif
    auto r=root.begin();
    auto t=target.begin();
    for(; r!=root.end(); ++r,++t){
        if(t==target.end() || *r!=*t) return false;
    }
    return true;
}

bool replace_snapshot_file(const fs::path& temporary, const fs::path& target, std::error_code& ec){
#ifdef _WIN32
    if(MoveFileExW(temporary.wstring().c_str(), target.wstring().c_str(),
                   MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)){
        ec.clear();
        return true;
    }
    ec = std::error_code((int)GetLastError(), std::system_category());
    return false;
#else
    fs::rename(temporary, target, ec);
    return !ec;
#endif
}

std::string absolute_path_string(const fs::path& p){
    std::error_code ec;
    fs::path abs = fs::absolute(p, ec);
    if(ec) abs = p;
    return abs.generic_string();
}

std::string preview(std::string s,size_t n=260){for(char&c:s) if(c=='\r'||c=='\n'||c=='\t') c=' '; while(s.find("  ")!=std::string::npos)s.erase(s.find("  "),1); if(s.size()>n)s=s.substr(0,n)+"..."; for(char&c:s)if(c=='|'||c=='"')c='\''; return s;}

bool labelish(const std::string& phrase){
    auto l=canonical_label(phrase);
    static const std::vector<std::string> bad={
        "mycelia ocr","source image","ocr ok","engine tesseract","downloads","chatgpt image",
        "eingangsvermerk","stadt leipzig","sozialamt","wohnraumversorgung","aktenzeichen","sachbearbeitung",
        "strasse hausnummer","straße hausnummer","telefon freiwillig","telefon reiwilig","plz ort","e mail","email",
        "lfd nr","geburtsdatum verwandtschaft","verwandtschaftsverhaltnis","verwandtschaftsverhältnis","dauerhaft",
        "name vorname","persoenliche daten","persönliche daten","haushaltsangehoerige","haushaltsangehörige",
        "beigefuegte nachweise","beigefiigte nachweise","beigefügte nachweise",
        "datum unterschrift","aktuelle wohnsituation","wohnungsart","bitte","hinweis",
        "einkommensnachweise","meldebescheinigung","personalausweise","mietzahlung","mietvertrag",
        "antrag auf ausstellung","wohnungsberechtigungsschein","wohn berechtigungsschein","mycelia sql dump import","create table","insert into","values text","text insert","varchar"};
    for(auto&b:bad) if(l.find(b)!=std::string::npos) return true;
    // Field labels are often OCR-merged with one or two values. If the phrase
    // starts as a known form label, never create a named-entity node from it.
    static const std::vector<std::string> starts={
        "strasse","straße","telefon","plz","ort","e mail","email","geburtsdatum",
        "staatsangehorigkeit","staatsangehörigkeit","aktuelle","wohnung","einkommen",
        "durchschnittliches","jahreseinkommen","unterlagen","sonstiges"};
    for(auto&s:starts) if(l.rfind(s,0)==0) return true;
    return false;
}
std::string clean_ocr_text(std::string t){
    // OCR text is evidence, not runtime telemetry. Strip engine/source metadata
    // before it enters the resonance field, otherwise MyceliaDB resonates with
    // file paths and OCR status instead of the form content.
    t=std::regex_replace(t,std::regex("\\r"),"\n");
    t=std::regex_replace(t,std::regex("\\f"),"\n");
    std::istringstream in(t); std::ostringstream out; std::string line;
    while(std::getline(in,line)){
        auto x=trim2(line);
        if(x.empty()){ out<<"\n"; continue; }
        auto lx=low(x);
        if(lx.rfind("mycelia_ocr_image_import",0)==0) continue;
        if(lx.rfind("source_image:",0)==0) continue;
        if(lx.find("engine=tesseract")!=std::string::npos) continue;
        if(lx=="ocr_ok" || lx.rfind("ocr_ok ",0)==0) continue;
        if(x.size()<=2 && std::string(".,;:|()[]{}'`´~_-").find(x[0])!=std::string::npos) continue;
        out<<x<<"\n";
    }
    auto r=out.str();
    while(r.find("\n\n\n")!=std::string::npos) r=std::regex_replace(r,std::regex("\\n\\n\\n+"),"\n\n");
    return r;
}
bool section_header(const std::string& t){
    if(t.empty()) return false;
    return std::regex_search(t,std::regex("^\\s*([0-9]{1,2}\\.|[0-9]{1,2}\\s+)\\s*[A-ZÄÖÜ]"));
}
std::string join(const std::vector<std::string>&a,size_t b=0){std::ostringstream o; for(size_t i=b;i<a.size();++i){if(i>b)o<<' '; o<<a[i];} return o.str();}
bool stop(const std::string& t){static const std::unordered_set<std::string> s={
"the","and","or","of","to","in","a","an","as","is","are","was","were","with","for","on","by",
"der","die","das","und","oder","im","am","an","zu","mit","von","für","auf","ein","eine","einer","eines","bei","zur","zum","sind","ist","ich","sie","er","wir",
"slide","role","function","plot","arc","core","target","version","final","basis","character","profile",
"create","table","insert","into","values","text","int","integer","varchar","mycelia","sql","dump","import",
"antrag","antragsteller","antragstellerin","adresse","geburtsdatum","formular","formulars","bezug","status","id","name","stadt",
"straße","strasse","hausnummer","telefon","freiwillig","email","e-mail","plz","ort","lfd","nr","eingangsvermerk","eingegangen","aktenzeichen","sachbearbeitung",
"persönliche","daten","haushaltsangehörige","einkommen","wohnsituation","nachweise","erklärung","datum","unterschrift","hinweis","seite","behörde","ausgefüllt",
"wohnraumversorgung","sozialamt","mietwohnung","eigentumswohnung","verlängerung","erstmalige","ausstellung","wohnungsgröße","monatlich","brutto","eur"}; return s.contains(low(t));}
std::vector<std::string> terms(const std::string& text){std::vector<std::string> r; std::string c; for(unsigned char u:text){if(std::isalnum(u)||u>=128)c.push_back((char)std::tolower(u)); else{if(c.size()>=2&&!stop(c))r.push_back(c); c.clear();}} if(c.size()>=2&&!stop(c))r.push_back(c); return r;}
bool cap(const std::string&w){return !w.empty() && std::isupper((unsigned char)w[0]);}
std::vector<std::string> words(const std::string& text){std::vector<std::string> r; std::string c; for(unsigned char u:text){char ch=(char)u; if(std::isalnum(u)||u>=128||ch=='-'||ch=='.')c.push_back(ch); else{if(!c.empty()){r.push_back(c); c.clear();} if(ch=='.'||ch==':'||ch==';'||ch=='\n'||ch=='\r') r.push_back("|");}} if(!c.empty())r.push_back(c); return r;}

bool person_like(const std::string& s){
    if(labelish(s)) return false;
    // exactly two to three name words; no dates, phone numbers, e-mail labels or long field text
    if(std::regex_search(s,std::regex("[0-9]{1,2}[\\./][0-9]{1,2}[\\./][0-9]{2,4}"))) return false;
    if(std::regex_search(s,std::regex("[0-9]{3,}"))) return false;
    if(s.find('@')!=std::string::npos) return false;
    return std::regex_match(s,std::regex("[A-ZÄÖÜ][A-Za-zÄÖÜäöüß\\-]{2,}(\\s+[A-ZÄÖÜ][A-Za-zÄÖÜäöüß\\-]{2,}){1,2}"));
}
void add_person_candidates_from_line(const std::string& line, std::vector<std::string>& out){
    std::regex r("([A-ZÄÖÜ][A-Za-zÄÖÜäöüß\\-]{2,}\\s+[A-ZÄÖÜ][A-Za-zÄÖÜäöüß\\-]{2,})");
    for(std::sregex_iterator it(line.begin(),line.end(),r), end; it!=end; ++it){
        auto v=(*it)[1].str();
        if(person_like(v)) out.push_back(v);
    }
}
std::vector<std::string> split_segments(const std::string& text){
    std::vector<std::string> r; std::istringstream in(text); std::string line,cur;
    auto flush=[&]{auto t=trim2(cur); if(!t.empty())r.push_back(t); cur.clear();};
    while(std::getline(in,line)){
        auto t=trim2(line);
        bool head=t.rfind("#",0)==0||t.rfind("Slide ",0)==0||section_header(t);
        if(head&&!cur.empty())flush();
        if(t.empty()){ if(cur.size()>350)flush(); continue; }
        if(!cur.empty())cur+="\n";
        cur+=line;
        // OCR form segments must stay local. Large segments make every entity
        // co-occur with every form label and destroy energetic locality.
        if(cur.size()>650)flush();
    }
    flush();
    if(r.empty()&&!text.empty())r.push_back(text);
    return r;
}
std::string title_of(const std::string&s){
    std::istringstream in(s); std::string l;
    while(std::getline(in,l)){
        l=trim2(l);
        if(l.empty()||labelish(l))continue;
        return preview(l,90);
    }
    return "segment";
}
std::vector<std::string> entities(const std::string& text){
    std::vector<std::string> out;
    auto add=[&](std::string v){
        v=trim2(v);
        v=std::regex_replace(v,std::regex("\\s+")," ");
        if(v.size()<2 || labelish(v)) return;
        int alpha=0; for(unsigned char c:v) if(std::isalpha(c)||c>=128) alpha++;
        if(alpha<2) return;
        out.push_back(v);
    };

    // OCR forms: extract values, not labels. We specifically pull person-like
    // values from lines and from the context after "Name, Vorname" without
    // swallowing dates/field labels.
    std::vector<std::string> lines; {std::istringstream in(text); std::string l; while(std::getline(in,l)){l=trim2(l); if(!l.empty())lines.push_back(l);}}
    for(size_t i=0;i<lines.size();++i){
        auto l=low(lines[i]);
        if((l.find("name")!=std::string::npos && l.find("vorname")!=std::string::npos) ||
           l=="name" || l=="vorname" || l.find("haushaltsangehörige")!=std::string::npos ||
           l.find("haushaltsangehoerige")!=std::string::npos){
            for(size_t j=i;j<lines.size() && j<i+6;++j) add_person_candidates_from_line(lines[j], out);
        }
        // All other lines may still contain names, but the regex keeps only
        // clean two-token names and rejects dates/numbers/labels.
        add_person_candidates_from_line(lines[i], out);
    }

    // Places and selected domain entities.
    static const std::unordered_set<std::string> places={"Leipzig","Antarctica","Berlin","Hamburg","Dresden","München","Munich","Köln"};
    for(auto&p:places){
        if(text.find(p)!=std::string::npos) add(p);
    }
    std::regex org("(Stadt\\s+Leipzig|Wohnbau\\s+Leipzig\\s+GmbH|Familienkasse\\s+Sachsen)");
    for(std::sregex_iterator it(text.begin(),text.end(),org), end; it!=end; ++it) add((*it)[1].str());

    // Generic capitalization NER for non-form prose. On OCR forms it is kept
    // conservative to avoid labels like "Straße Hausnummer Telefon".
    auto w=words(text);
    for(size_t i=0;i<w.size();++i){
        if(w[i]=="|"||!cap(w[i])||stop(w[i]))continue;
        std::string ph=w[i]; size_t cnt=1,j=i+1;
        while(j<w.size()&&cnt<3&&w[j]!="|"&&cap(w[j])&&!stop(w[j])){ph+=" "+w[j]; ++cnt; ++j;}
        if(cnt>=2 && person_like(ph)){add(ph); i=j-1;}
    }
    std::sort(out.begin(),out.end()); out.erase(std::unique(out.begin(),out.end()),out.end()); return out;
}


struct InheritedFieldCell {
    std::string fieldLabel;
    std::string fieldKind;
    std::string value;
    std::string targetEntity;
    double confidence{0.60};
};

bool relation_value_candidate(const std::string& raw){
    auto v=trim2(std::regex_replace(raw,std::regex("\\s+")," "));
    if(v.size()<3 || v.size()>48) return false;
    if(labelish(v) || person_like(v)) return false;
    if(std::regex_search(v,std::regex("[0-9@]"))) return false;
    auto c=canonical_label(v);
    if(c.empty() || stop(c)) return false;
    static const std::vector<std::string> structural={
        "dauerhaft","wohnhaft","seit","geburtsdatum","name","vorname","lfd","nr",
        "haushalt","haushaltsangehorige","haushaltsangehörige","verwandtschaft",
        "personen","angeben","bitte","gesamt","insgesamt","antragsteller"
    };
    for(auto&s:structural) if(c.find(s)!=std::string::npos) return false;
    int alpha=0; for(unsigned char ch:v) if(std::isalpha(ch)||ch>=128) alpha++;
    if(alpha<3) return false;
    return true;
}

std::string infer_field_kind_from_header(const std::string& header){
    auto h=canonical_label(header);
    // This is not a value whitelist. It is field inheritance: the column/header
    // creates semantic tension, and every clean value under/near the field
    // inherits the kind.
    if(h.find("verwandtschaft")!=std::string::npos || h.find("beziehung")!=std::string::npos ||
       h.find("verhaeltnis")!=std::string::npos || h.find("verhaltnis")!=std::string::npos)
        return "relationship";
    if(h.find("wohnort")!=std::string::npos || h.find("plz ort")!=std::string::npos ||
       h.find("anschrift")!=std::string::npos || h.find("strasse")!=std::string::npos || h.find("straße")!=std::string::npos)
        return "address";
    if(h.find("geburtsdatum")!=std::string::npos || h.find("datum")!=std::string::npos)
        return "date";
    if(h.find("einkommen")!=std::string::npos || h.find("miete")!=std::string::npos ||
       h.find("betrag")!=std::string::npos)
        return "amount";
    if(h.find("name")!=std::string::npos || h.find("vorname")!=std::string::npos)
        return "person";
    return {};
}

std::string normalize_field_label(const std::string& header){
    auto h=canonical_label(header);
    if(h.find("verwandtschaft")!=std::string::npos || h.find("beziehung")!=std::string::npos)
        return "Verwandtschaftsverhältnis";
    if(h.find("geburtsdatum")!=std::string::npos) return "Geburtsdatum";
    if(h.find("plz")!=std::string::npos && h.find("ort")!=std::string::npos) return "PLZ/Ort";
    if(h.find("strasse")!=std::string::npos || h.find("straße")!=std::string::npos) return "Straße/Hausnummer";
    if(h.find("einkommen")!=std::string::npos) return "Einkommen";
    if(h.find("name")!=std::string::npos && h.find("vorname")!=std::string::npos) return "Name/Vorname";
    return preview(header,64);
}

std::vector<InheritedFieldCell> infer_field_cells(const std::string& text){
    std::vector<InheritedFieldCell> out;
    auto push=[&](InheritedFieldCell c){
        c.value=trim2(std::regex_replace(c.value,std::regex("\\s+")," "));
        c.targetEntity=trim2(std::regex_replace(c.targetEntity,std::regex("\\s+")," "));
        if(c.fieldKind.empty()||c.value.empty()) return;
        if(c.fieldKind=="relationship" && !relation_value_candidate(c.value)) return;
        for(auto&x:out){
            if(canonical_label(x.fieldKind)==canonical_label(c.fieldKind) &&
               canonical_label(x.value)==canonical_label(c.value) &&
               canonical_label(x.targetEntity)==canonical_label(c.targetEntity)) return;
        }
        out.push_back(c);
    };

    std::vector<std::string> lines;
    { std::istringstream in(text); std::string line; while(std::getline(in,line)){line=trim2(line); if(!line.empty()) lines.push_back(line);} }

    // 1) Explicit row pattern: Person + birth date + value + since date.
    // The value is not recognized through a whitelist. It inherits the semantic
    // type from the nearby column/header "Verwandtschaftsverhältnis".
    bool hasRelationshipField=false;
    for(auto&l:lines){
        auto kind=infer_field_kind_from_header(l);
        if(kind=="relationship") hasRelationshipField=true;
    }
    if(hasRelationshipField){
        std::string flat=text;
        flat=std::regex_replace(flat,std::regex("\\s+")," ");
        std::regex row("([A-ZÄÖÜ][A-Za-zÄÖÜäöüß\\-]{2,}\\s+[A-ZÄÖÜ][A-Za-zÄÖÜäöüß\\-]{2,})\\s+([0-9]{1,2}[\\./][0-9]{1,2}[\\./][0-9]{2,4})\\s+([A-Za-zÄÖÜäöüß\\-]{3,}(?:\\s+[A-Za-zÄÖÜäöüß\\-]{3,}){0,2})\\s+([0-9]{1,2}[\\./][0-9]{1,2}[\\./][0-9]{2,4})");
        for(std::sregex_iterator it(flat.begin(),flat.end(),row), end; it!=end; ++it){
            auto person=(*it)[1].str();
            auto value=(*it)[3].str();
            if(person_like(person)){
                push({"Verwandtschaftsverhältnis","relationship",value,person,0.94});
            }
        }
    }

    // 2) Header-window inheritance. After a relationship header, short clean
    // non-label values that occur close to person/date patterns become
    // relationship cells. This catches OCR layouts where rows are broken across
    // several lines.
    for(size_t i=0;i<lines.size();++i){
        auto kind=infer_field_kind_from_header(lines[i]);
        if(kind.empty()) continue;
        auto label=normalize_field_label(lines[i]);
        size_t end=std::min(lines.size(), i+9);
        for(size_t j=i+1;j<end;++j){
            auto line=lines[j];
            std::vector<std::string> ps; add_person_candidates_from_line(line, ps);
            // Remove person names, dates and long numeric fields; remaining
            // small text cells are value candidates for the inherited field.
            std::string residual=line;
            for(auto&p:ps) residual=std::regex_replace(residual,std::regex(p)," ");
            residual=std::regex_replace(residual,std::regex("[0-9]{1,2}[\\./][0-9]{1,2}[\\./][0-9]{2,4}")," ");
            residual=std::regex_replace(residual,std::regex("\\b[0-9]+([,.][0-9]+)?\\b")," ");
            residual=std::regex_replace(residual,std::regex("\\s+")," ");
            if(kind=="relationship"){
                std::istringstream rin(residual); std::string tok;
                while(rin>>tok){
                    tok=trim2(std::regex_replace(tok,std::regex("[^A-Za-zÄÖÜäöüß\\-]"),""));
                    if(relation_value_candidate(tok)){
                        std::string target=ps.empty()?std::string{}:ps.front();
                        push({label,kind,tok,target,0.72});
                    }
                }
            }
        }
    }

    // 3) Generic key/value lines. This is used for future forms: whatever
    // header creates the type, values inherit it dynamically.
    std::regex kv("^\\s*([^:]{3,80})\\s*[:=]\\s*(.{2,120})$");
    for(auto&line:lines){
        std::smatch m;
        if(std::regex_search(line,m,kv)){
            auto kind=infer_field_kind_from_header(m[1].str());
            if(kind.empty()) continue;
            auto label=normalize_field_label(m[1].str());
            auto val=trim2(m[2].str());
            if(kind=="relationship") push({label,kind,val,"",0.86});
        }
    }

    return out;
}

std::string merge_ocr_outputs(const std::vector<std::string>& texts){
    std::unordered_set<std::string> seen;
    std::ostringstream out;
    for(auto&t:texts){
        std::istringstream in(t);
        std::string line;
        while(std::getline(in,line)){
            auto x=trim2(line);
            if(x.empty()) continue;
            auto key=canonical_label(x);
            if(key.size()<3) continue;
            if(seen.insert(key).second) out<<x<<"\n";
        }
        out<<"\n";
    }
    return out.str();
}

std::string sql_text(const std::string& sql){std::ostringstream o; o<<"MYCELIA_SQL_DUMP_IMPORT\n"; bool q=false; char qc=0; std::string lit; for(char ch:sql){if((ch=='\''||ch=='"')&&!q){q=true; qc=ch; lit.clear(); continue;} if(q&&ch==qc){q=false; if(!lit.empty())o<<lit<<"\n"; continue;} if(q)lit+=ch; else if(std::isalnum((unsigned char)ch)||(unsigned char)ch>=128)o<<ch; else o<<' ';} return o.str();}

std::string esc_snapshot(const std::string& in){
    std::ostringstream o;
    for(unsigned char c: in){
        switch(c){
            case '\\': o<<"\\\\"; break;
            case '\n': o<<"\\n"; break;
            case '\r': o<<"\\r"; break;
            case '\t': o<<"\\t"; break;
            default: o<<(char)c; break;
        }
    }
    return o.str();
}
std::string unesc_snapshot(const std::string& in){
    std::string out; bool esc=false;
    for(char c: in){
        if(esc){
            if(c=='n') out.push_back('\n');
            else if(c=='r') out.push_back('\r');
            else if(c=='t') out.push_back('\t');
            else out.push_back(c);
            esc=false;
        } else if(c=='\\') esc=true;
        else out.push_back(c);
    }
    if(esc) out.push_back('\\');
    return out;
}
std::vector<std::string> split_tab_preserve(const std::string& line){
    std::vector<std::string> v; std::string cur;
    for(char c: line){ if(c=='\t'){ v.push_back(cur); cur.clear(); } else cur.push_back(c); }
    v.push_back(cur); return v;
}
struct Hit{std::string id,kind,label,evidence; double energy{};};

std::string qarg(std::string s){
#ifdef _WIN32
    std::string r="\""; for(char c:s){ if(c=='"') r+="\\\""; else r+=c; } r+="\""; return r;
#else
    std::string r="'"; for(char c:s){ if(c=='\'') r+="'\\''"; else r+=c; } r+="'"; return r;
#endif
}
std::string getenvs(const char* k){const char* v=std::getenv(k); return v?std::string(v):std::string{};}
std::string tesseract_exe(){
    auto e=getenvs("MYCELIA_TESSERACT");
    if(!e.empty())return e;
#ifdef _WIN32
    for(const char* p: {
        "C:\\Program Files\\Tesseract-OCR\\tesseract.exe",
        "C:\\Program Files (x86)\\Tesseract-OCR\\tesseract.exe"
    }) if(fs::exists(p)) return p;
#endif
    return "tesseract";
}
int run_cmd_silent(const std::string& cmd){
#ifdef _WIN32
    // Windows cmd.exe has fragile quote rules when the executable path starts
    // with a quoted "C:\Program Files\..." command. /S /C plus one outer
    // quote pair preserves the quoted executable, quoted image path and
    // redirection targets reliably for Tesseract OCR.
    std::string wrapped = "cmd /S /C \"" + cmd + "\"";
    return std::system(wrapped.c_str());
#else
    return std::system(cmd.c_str());
#endif
}
bool has_tesseract(){
    auto tmp=(fs::temp_directory_path()/("mycelia_tesseract_probe.txt")).string();
#ifdef _WIN32
    std::string cmd=qarg(tesseract_exe())+" --version > "+qarg(tmp)+" 2>&1";
#else
    std::string cmd=qarg(tesseract_exe())+" --version > "+qarg(tmp)+" 2>&1";
#endif
    int rc=run_cmd_silent(cmd); return rc==0;
}
std::string ocr_image_to_text(const std::string& imagePath,std::string& diagnostic){
    auto stamp=std::to_string(std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::system_clock::now().time_since_epoch()).count());
    fs::path outbase=fs::temp_directory_path()/("mycelia_ocr_"+stamp);
    fs::path log=fs::temp_directory_path()/("mycelia_ocr_"+stamp+".log");
    auto exe=tesseract_exe();

    // Multi-pass OCR: forms/tables often fail with a single PSM. We combine
    // unique lines from several segmentation modes so relationship cells such
    // as "Ehemann" survive more often.
    struct Attempt { const char* lang; int psm; };
    std::vector<Attempt> attempts={{"deu+eng",6},{"deu+eng",4},{"deu+eng",11},{"eng",6}};
    std::vector<std::string> successful;
    std::ostringstream diaglog;

    int idx=0;
    for(auto&a:attempts){
        fs::path base=outbase; base += ("_"+std::to_string(++idx));
        fs::path outfile=base; outfile += ".txt";
        std::string cmd=qarg(exe)+" "+qarg(imagePath)+" "+qarg(base.string())+" -l "+a.lang+" --psm "+std::to_string(a.psm)+" > "+qarg(log.string())+" 2>&1";
        int rc=run_cmd_silent(cmd);
        auto text=read_file(outfile.string());
        diaglog<<"psm="<<a.psm<<" lang="<<a.lang<<" rc="<<rc<<" bytes="<<text.size()<<" ";
        if(rc==0 && !trim2(text).empty()) successful.push_back(text);
        std::error_code ec; fs::remove(outfile,ec);
    }

    if(!successful.empty()){
        auto merged=merge_ocr_outputs(successful);
        diagnostic="OCR_OK engine=tesseract exe="+exe+" passes="+std::to_string(successful.size())+" bytes="+std::to_string(merged.size());
        std::error_code ec; fs::remove(log,ec);
        return merged;
    }

    diagnostic="OCR_FAIL engine=tesseract exe="+exe+" attempts="+preview(diaglog.str(),260)+" log="+preview(read_file(log.string()),360)+" hint=try_manual_tesseract_command";
    std::error_code ec; fs::remove(log,ec);
    return {};
}
}

MyceliaEngine::MyceliaEngine(){gpu_.load();}
std::string MyceliaEngine::help() const{return "MYCELIA COMMANDS: PING | SPAWN | LINK | MUTATE | ERASE_NODE | GET | TRACE | PULSE | INGEST_TEXT | INGEST_SQL | INGEST_OCR_IMAGE | OCR_STATUS | QUERY_FIELD | EXPLAIN_RESONANCE | GET_NEIGHBORS | FIELD_STATUS | SAVE_DB | LOAD_DB | CLEAR_DB | GET_MEDIA_FOR_NODE | GET_IMAGE_INFO | GPU_STATUS";}

void MyceliaEngine::add_node(const std::string&id,const std::string&kind,const std::string&label){auto&n=nodes_[id]; n.id=id; if(!kind.empty())n.props["kind"]=kind; if(!label.empty())n.props["label"]=label;}
void MyceliaEngine::add_link(const std::string&f,const std::string&t,double w,const std::string&k){if(f.empty()||t.empty()||f==t)return; links_.push_back({f,t,w,k}); adjacency_[f].insert(t); adjacency_[t].insert(f);}
void MyceliaEngine::index_document(DocumentCell doc){
    const auto did=doc.id;
    auto documentInheritedCells=infer_field_cells(doc.text);
    for(auto&t:terms(doc.text))doc.termFrequency[t]++;
    add_node(did,"document",did); nodes_[did].props["type"]=doc.type; nodes_[did].props["path"]=doc.path; nodes_[did].props["terms"]=std::to_string(doc.termFrequency.size());
    int n=0; for(auto&st:split_segments(doc.text)){SegmentCell s; s.documentId=did; s.id=did+"#seg:"+std::to_string(++n); s.title=title_of(st); s.text=st; add_node(s.id,"segment",s.title); nodes_[s.id].props["doc"]=did; nodes_[s.id].props["preview"]=preview(st,180); add_link(did,s.id,0.95,"contains_segment");
        std::unordered_map<std::string,int> freq; for(auto&t:terms(st))freq[t]++; std::vector<std::pair<std::string,int>> rs(freq.begin(),freq.end()); std::sort(rs.begin(),rs.end(),[](auto&a,auto&b){return a.second>b.second;});
        int kept=0; for(auto&[t,f]:rs){if(kept++>=48)break; auto tid=node_id("term",t); add_node(tid,"term",t); add_link(s.id,tid,std::min(0.82,0.22+std::log(1.0+f)*0.18),"term_resonance"); segmentIndex_[t].insert(s.id);}
        std::vector<std::string> es; for(auto&e:entities(st)){std::string kind="person_or_named_entity", pref="entity"; if(e=="Leipzig"||e=="Antarctica"||e=="Berlin"||e=="Hamburg"||e=="Dresden"){kind="place"; pref="place";} auto eid=node_id(pref,e); add_node(eid,kind,e); add_link(eid,s.id,0.93,"evidence"); add_link(eid,did,0.55,"mentioned_in"); es.push_back(eid);}
        for(auto&cell:infer_field_cells(st)){
            auto fid=node_id("field",cell.fieldLabel);
            add_node(fid,"semantic_field",cell.fieldLabel);
            nodes_[fid].props["inferred_kind"]=cell.fieldKind;
            add_link(fid,s.id,0.88,"field_evidence");

            std::string pref=cell.fieldKind=="relationship"?"relation":"field_value";
            auto vid=node_id(pref,cell.value);
            add_node(vid,cell.fieldKind,cell.value);
            nodes_[vid].props["inherited_from"]=cell.fieldLabel;
            nodes_[vid].props["confidence"]=std::to_string(cell.confidence);
            add_link(fid,vid,0.97,"field_inheritance");
            add_link(vid,s.id,0.96,"inherited_value_evidence");
            add_link(vid,did,0.48,"inherited_value_in_document");

            if(!cell.targetEntity.empty()){
                auto tid=node_id("entity",cell.targetEntity);
                add_node(tid,"person_or_named_entity",cell.targetEntity);
                add_link(vid,tid,0.92,"role_of");
                add_link(tid,s.id,0.85,"field_row_evidence");
            }
        }
        for(size_t i=0;i<es.size();++i)for(size_t j=i+1;j<es.size();++j)add_link(es[i],es[j],0.64,"co_occurs");
        doc.segmentIds.push_back(s.id); segments_[s.id]=std::move(s);
    }

    // Document-level field inheritance: OCR/layout segmentation can separate
    // the column header from the row values. MyceliaDB therefore infers field
    // cells once over the whole document and then attaches each inherited value
    // to the closest evidence segment. This is the automatic mechanism that
    // creates relation:Ehemann from a Verwandtschaftsverhältnis column without
    // a fixed relationship whitelist.
    for(auto&cell:documentInheritedCells){
        auto fid=node_id("field",cell.fieldLabel);
        add_node(fid,"semantic_field",cell.fieldLabel);
        nodes_[fid].props["inferred_kind"]=cell.fieldKind;
        add_link(fid,did,0.42,"field_in_document");

        std::string pref=cell.fieldKind=="relationship"?"relation":"field_value";
        auto vid=node_id(pref,cell.value);
        add_node(vid,cell.fieldKind,cell.value);
        nodes_[vid].props["inherited_from"]=cell.fieldLabel;
        nodes_[vid].props["confidence"]=std::to_string(cell.confidence);
        add_link(fid,vid,0.99,"field_inheritance");
        add_link(vid,did,0.54,"inherited_value_in_document");

        std::string bestSeg;
        for(auto&sid:doc.segmentIds){
            auto it=segments_.find(sid);
            if(it==segments_.end()) continue;
            auto stlow=canonical_label(it->second.text);
            if(stlow.find(canonical_label(cell.value))!=std::string::npos &&
               (cell.targetEntity.empty() || stlow.find(canonical_label(cell.targetEntity))!=std::string::npos)){
                bestSeg=sid; break;
            }
        }
        if(bestSeg.empty()){
            for(auto&sid:doc.segmentIds){
                auto it=segments_.find(sid);
                if(it!=segments_.end() && canonical_label(it->second.text).find(canonical_label(cell.fieldLabel))!=std::string::npos){
                    bestSeg=sid; break;
                }
            }
        }
        if(!bestSeg.empty()) add_link(vid,bestSeg,0.98,"inherited_value_evidence");

        if(!cell.targetEntity.empty()){
            auto tid=node_id("entity",cell.targetEntity);
            add_node(tid,"person_or_named_entity",cell.targetEntity);
            add_link(vid,tid,0.94,"role_of");
            if(!bestSeg.empty()) add_link(tid,bestSeg,0.86,"field_row_evidence");
        }
    }

    docs_[did]=std::move(doc); for(auto&[t,f]:docs_[did].termFrequency)inverted_[t].insert(did);
}
std::string MyceliaEngine::ingest_text_file(const std::string&p,const std::string&ex,const std::string&type){auto text=read_file(p); if(text.empty())return"ERR INGEST_TEXT cannot read file: "+p; fs::path fp(p); DocumentCell d; d.id=ex.empty()?("doc:"+sanitize(fp.stem().string())):ex; d.path=p; d.type=type; d.text=text; auto bn=nodes_.size(), bl=links_.size(); index_document(std::move(d)); return "OK INGESTED_TEXT id="+(ex.empty()?("doc:"+sanitize(fp.stem().string())):ex)+" bytes="+std::to_string(text.size())+" nodes_added="+std::to_string(nodes_.size()-bn)+" links_added="+std::to_string(links_.size()-bl)+" model=resonance_field";}
std::string MyceliaEngine::ingest_sql_dump(const std::string&p,const std::string&ex){auto sql=read_file(p); if(sql.empty())return"ERR INGEST_SQL cannot read file: "+p; fs::path fp(p); DocumentCell d; d.id=ex.empty()?("sql:"+sanitize(fp.stem().string())):ex; d.path=p; d.type="sql-dump"; d.text=sql_text(sql); auto bn=nodes_.size(), bl=links_.size(); auto id=d.id; index_document(std::move(d)); return "OK INGESTED_SQL id="+id+" source_bytes="+std::to_string(sql.size())+" nodes_added="+std::to_string(nodes_.size()-bn)+" links_added="+std::to_string(links_.size()-bl)+" model=resonance_field";}

std::string MyceliaEngine::ocr_status() const{
    return std::string("OCR_STATUS engine=tesseract mode=external_cli available=") + (has_tesseract()?"yes":"no") + " exe=" + tesseract_exe() + " env=MYCELIA_TESSERACT";
}
std::string MyceliaEngine::ingest_ocr_image(const std::string&p,const std::string&ex){
    if(!fs::exists(p))return "ERR INGEST_OCR_IMAGE file not found: "+p;
    std::string diag; auto text=ocr_image_to_text(p,diag);
    if(trim2(text).empty())return "ERR INGEST_OCR_IMAGE "+diag+" path="+p;
    fs::path fp(p); DocumentCell d; d.id=ex.empty()?("ocr:"+sanitize(fp.stem().string())):ex; d.path=p; d.type="ocr-image";
    d.text=clean_ocr_text(text);

    std::error_code ec;
    fs::create_directories("data/media", ec);
    auto sha=weak_hash_file(p);
    auto ext=file_ext_lower(p);
    fs::path stored=fs::path("data/media")/(sha+"."+ext);
    fs::copy_file(p, stored, fs::copy_options::overwrite_existing, ec);

    MediaAsset media;
    media.id="media:image:"+sanitize(sha);
    media.sourcePath=p;
    media.storedPath=absolute_path_string(stored);
    media.mime=mime_for_path(p);
    media.sha=sha;
    media.documentId=d.id;
    media.bytes=fs::exists(stored)?fs::file_size(stored,ec):0;
    d.mediaId=media.id;

    auto bn=nodes_.size(), bl=links_.size(); auto id=d.id; auto mid=media.id;
    media_[mid]=media;
    index_document(std::move(d));
    add_node(mid,"image_media",fp.filename().string());
    nodes_[mid].props["mime"]=media_[mid].mime;
    nodes_[mid].props["stored"]=media_[mid].storedPath;
    nodes_[mid].props["source"]=media_[mid].sourcePath;
    nodes_[mid].props["sha"]=media_[mid].sha;
    add_link(id,mid,0.99,"derived_from_image");
    add_link(mid,id,0.99,"source_for_ocr_document");
    for(const auto& sid: docs_[id].segmentIds) add_link(sid,mid,0.70,"evidenced_by_image");

    return "OK INGESTED_OCR_IMAGE id="+id+" image="+p+" media="+mid+" stored="+media_[mid].storedPath+
           " ocr_chars="+std::to_string(text.size())+" nodes_added="+std::to_string(nodes_.size()-bn)+
           " links_added="+std::to_string(links_.size()-bl)+" model=resonance_field "+diag;
}
std::string MyceliaEngine::list_docs() const{std::ostringstream o; o<<"DOCS"; for(auto&[id,d]:docs_)o<<" "<<id<<"|type="<<d.type<<"|terms="<<d.termFrequency.size()<<"|segments="<<d.segmentIds.size(); return o.str();}
std::string MyceliaEngine::get_doc(const std::string&id) const{auto it=docs_.find(id); if(it==docs_.end())return"ERR missing document"; return "DOC "+id+" type="+it->second.type+" path="+it->second.path+" preview="+preview(it->second.text,900);}
std::string MyceliaEngine::field_status() const{std::map<std::string,size_t> k; for(auto&[id,n]:nodes_){auto it=n.props.find("kind"); k[it==n.props.end()?"unknown":it->second]++;} std::ostringstream o; o<<"FIELD_STATUS docs="<<docs_.size()<<" segments="<<segments_.size()<<" nodes="<<nodes_.size()<<" links="<<links_.size(); for(auto&[a,b]:k)o<<" "<<a<<"="<<b; return o.str();}
std::string MyceliaEngine::get_neighbors(const std::string&id) const{auto it=adjacency_.find(id); if(it==adjacency_.end())return"NEIGHBORS 0"; std::ostringstream o; o<<"NEIGHBORS "<<it->second.size(); int c=0; for(auto&n:it->second){if(c++>40)break; o<<" | NODE id="<<n;} return o.str();}

std::string MyceliaEngine::get_image_info(const std::string& id) const{
    auto it=media_.find(id);
    if(it==media_.end()) return "MEDIA 0";
    const auto& m=it->second;
    std::ostringstream o;
    o<<"MEDIA 1 id="<<m.id<<" mime="<<m.mime<<" bytes="<<m.bytes<<" sha="<<m.sha
     <<" doc="<<m.documentId<<" stored="<<m.storedPath<<" source="<<m.sourcePath;
    return o.str();
}

std::string MyceliaEngine::get_media_for_node(const std::string& id) const{
    std::string docId;
    if(docs_.contains(id)) docId=id;
    auto sit=segments_.find(id);
    if(sit!=segments_.end()) docId=sit->second.documentId;
    if(docId.empty()){
        auto ai=adjacency_.find(id);
        if(ai!=adjacency_.end()){
            for(const auto& nb: ai->second){
                if(segments_.contains(nb)){ docId=segments_.at(nb).documentId; break; }
                if(docs_.contains(nb)){ docId=nb; break; }
            }
        }
    }
    if(docId.empty()) return "MEDIA 0";
    auto dit=docs_.find(docId);
    if(dit==docs_.end() || dit->second.mediaId.empty()) return "MEDIA 0 doc="+docId;
    auto mit=media_.find(dit->second.mediaId);
    if(mit==media_.end()) return "MEDIA 0 doc="+docId;
    const auto& m=mit->second;
    std::ostringstream o;
    o<<"MEDIA 1 id="<<m.id<<" mime="<<m.mime<<" bytes="<<m.bytes<<" sha="<<m.sha
     <<" doc="<<m.documentId<<" stored="<<m.storedPath<<" source="<<m.sourcePath;
    return o.str();
}

std::string MyceliaEngine::query_field(const std::vector<std::string>&args,bool explain) const{
    if(args.empty()) return "ERR QUERY_FIELD requires <terms...>";
    auto q=join(args);
    auto ts=terms(q);
    std::unordered_map<std::string,double> e;
    auto contains_all=[&](const std::string&s){auto l=low(s); for(auto&t:ts) if(l.find(low(t))==std::string::npos)return false; return true;};
    auto contains_any=[&](const std::string&s){auto l=low(s); for(auto&t:ts) if(l.find(low(t))!=std::string::npos)return true; return false;};
    auto term_hits=[&](const std::string&s){int c=0; auto l=low(s); for(auto&t:ts) if(l.find(low(t))!=std::string::npos)++c; return c;};
    auto proximity_boost=[&](const std::string&s){
        auto l=low(s);
        if(ts.empty()) return 0.0;
        std::vector<size_t> pos;
        for(auto&t:ts){
            auto p=l.find(low(t));
            if(p==std::string::npos) return 0.0;
            pos.push_back(p);
        }
        auto mm=std::minmax_element(pos.begin(),pos.end());
        double span=double(*mm.second-*mm.first+1);
        double density=double(ts.size())/std::max(1.0,double(l.size())/80.0);
        return 1.0 + 260.0/(32.0+span) + std::min(4.0,density);
    };

    // Seed exact term nodes and local term evidence.
    for(auto&t:ts){auto tid=node_id("term",t); if(nodes_.contains(tid))e[tid]+=1.0; auto si=segmentIndex_.find(t); if(si!=segmentIndex_.end())for(auto&sg:si->second)e[sg]+=0.72;}

    // Seed value nodes by partial token match too. This is essential for
    // compositional queries such as "Ehemann Hartmann": relation:ehemann and
    // entity:jonas_hartmann are two neighboring nodes, not one label.
    for(auto&[id,n]:nodes_){
        auto k=n.props.contains("kind")?n.props.at("kind"):"";
        auto lab=n.props.contains("label")?n.props.at("label"):id;
        if(!(k=="person_or_named_entity"||k=="place"||k=="entity"||k=="relationship"||k=="semantic_field")) continue;
        auto ql=low(q), ll=low(lab);
        double boost=0.0;
        if(ll==ql) boost=220.0;
        else if(contains_all(lab)) boost=95.0;
        else if(contains_any(lab)){
            int hits=term_hits(lab);
            boost=12.0*hits;
            if(k=="relationship") boost*=4.0;
            if(k=="person_or_named_entity"||k=="entity") boost*=2.3;
            if(k=="semantic_field") boost*=0.55;
        }
        if(boost>0.0)e[id]+=boost;
    }

    // Segment seeding is proximity-aware. A short row such as
    // "2 Jonas Hartmann 22.08.1990 Ehemann 01.06.2018" must outrank a huge OCR
    // block that merely contains Lena Hartmann and Ehemann far apart.
    for(auto&[id,s]:segments_){
        if(contains_all(s.text)){
            double prox=proximity_boost(s.text);
            double boost=18.0*prox;
            if(low(s.text).find(low(q))!=std::string::npos) boost=140.0;
            if(s.text.size()<180) boost*=2.8;
            else if(s.text.size()<360) boost*=1.9;
            else if(s.text.size()>900) boost*=0.45;
            e[id]+=boost;
        }
    }
    if(e.empty())return "RESONANCE_RESULTS 0 query=\""+preview(q,80)+"\"";
    auto cur=e; for(int d=0;d<4;++d){std::unordered_map<std::string,double> next; for(auto&[id,en]:cur){auto ai=adjacency_.find(id); if(ai==adjacency_.end())continue; for(auto&nb:ai->second){double w=0.25; for(auto&l:links_)if((l.from==id&&l.to==nb)||(l.from==nb&&l.to==id))w=std::max(w,l.weight); double de=en*w*0.62; if(de>0.005)next[nb]+=de;}} for(auto&[id,en]:next)e[id]+=en; cur=std::move(next); if(cur.empty())break;}
    auto ev=[&](const std::string&id){if(segments_.contains(id))return segments_.at(id).title+" :: "+preview(segments_.at(id).text,explain?520:300); auto ai=adjacency_.find(id); if(ai!=adjacency_.end())for(auto&nb:ai->second)if(segments_.contains(nb))return segments_.at(nb).title+" :: "+preview(segments_.at(nb).text,explain?520:300); return std::string{};};
    std::vector<Hit> h; for(auto&[id,en]:e){auto ni=nodes_.find(id); if(ni==nodes_.end())continue; auto k=ni->second.props.contains("kind")?ni->second.props.at("kind"):"node"; if(!(k=="document"||k=="segment"||k=="person_or_named_entity"||k=="place"||k=="entity"||k=="relationship"||k=="semantic_field"))continue; double de=en; auto lab=ni->second.props.contains("label")?ni->second.props.at("label"):id; if(k=="document")de*=0.18; else if(k=="segment"){
            double prox=proximity_boost(segments_.contains(id)?segments_.at(id).text:lab);
            de*=1.10 + std::min(2.8,prox*0.35);
            if(segments_.contains(id) && segments_.at(id).text.size()<220 && contains_all(segments_.at(id).text)) de*=2.4;
            if(low(segments_.contains(id)?segments_.at(id).text:lab).find(low(q))!=std::string::npos) de*=1.45;
        } else {
            de*=1.05;
            auto ll=low(lab), ql=low(q);
            bool all=contains_all(lab);
            bool any=contains_any(lab);
            if(ll==ql) de*=4.2;
            else if(all) de*=2.0;
            else if(any){
                if(k=="relationship") de*=1.45;
                else if(k=="person_or_named_entity"||k=="entity") de*=0.82;
                else de*=0.38;
            } else de*=0.10;
            if(labelish(lab)) de*=0.02;
        } h.push_back({id,k,lab,ev(id),de});}
    std::sort(h.begin(),h.end(),[](auto&a,auto&b){return a.energy>b.energy;}); if(h.size()>12)h.resize(12); std::ostringstream o; o<<(explain?"RESONANCE_EXPLAIN ":"RESONANCE_RESULTS ")<<h.size()<<" query=\""<<preview(q,90)<<"\" engine=energy_diffusion depth=4 decay=0.62"; int r=0; for(auto&x:h)o<<" | HIT rank="<<++r<<" id="<<x.id<<" energy="<<std::fixed<<std::setprecision(3)<<x.energy<<" kind="<<x.kind<<" label=\""<<preview(x.label,100)<<"\" evidence=\""<<preview(x.evidence,explain?560:320)<<"\""; return o.str();
}


void MyceliaEngine::clear_all(){
    nodes_.clear();
    links_.clear();
    manualNodes_.clear();
    docs_.clear();
    segments_.clear();
    inverted_.clear();
    segmentIndex_.clear();
    adjacency_.clear();
    media_.clear();
}

std::string MyceliaEngine::save_db(const std::string& path) const{
    if(!snapshot_path_allowed(path)) return "ERR SAVE_DB path denied";
    fs::path target(path);
    fs::path temporary = target;
    temporary += ".tmp";

    std::ofstream out(temporary, std::ios::binary | std::ios::trunc);
    if(!out) return "ERR SAVE_DB cannot write: " + temporary.string();

    out << "MYCELIADB_SNAPSHOT_V2\n";
    out << "DOC_COUNT\t" << docs_.size() << "\n";
    for(const auto& [id,d]: docs_){
        out << "DOC\t" << esc_snapshot(id) << "\t" << esc_snapshot(d.path) << "\t"
            << esc_snapshot(d.type) << "\t" << esc_snapshot(d.text) << "\t" << esc_snapshot(d.mediaId) << "\n";
    }

    out << "MEDIA_COUNT\t" << media_.size() << "\n";
    fs::path mediaDir = fs::path(path + ".media");
    std::error_code ec;
    fs::create_directories(mediaDir, ec);
    for(const auto& [id,m]: media_){
        fs::path src=m.storedPath;
        fs::path dst=mediaDir / fs::path(m.storedPath).filename();
        if(fs::exists(src)) fs::copy_file(src,dst,fs::copy_options::overwrite_existing,ec);
        out << "MEDIA\t" << esc_snapshot(id) << "\t" << esc_snapshot(m.sourcePath) << "\t"
            << esc_snapshot(dst.string()) << "\t" << esc_snapshot(m.mime) << "\t"
            << esc_snapshot(m.sha) << "\t" << esc_snapshot(m.documentId) << "\t" << m.bytes << "\n";
    }

    // V2: persist only nodes explicitly created through SPAWN. Derived document,
    // segment, term, entity and media nodes are still rebuilt from primary data.
    out << "MANUAL_NODE_COUNT\t" << manualNodes_.size() << "\n";
    for(const auto& id : manualNodes_){
        auto it = nodes_.find(id);
        if(it == nodes_.end()) continue;
        const auto& n = it->second;
        out << "MANUAL_NODE\t" << esc_snapshot(n.id) << "\t"
            << std::setprecision(17) << n.energy << "\t" << n.props.size() << "\n";
        for(const auto& [key,value] : n.props){
            out << "PROP\t" << esc_snapshot(n.id) << "\t"
                << esc_snapshot(key) << "\t" << esc_snapshot(value) << "\n";
        }
    }

    size_t manualLinkCount = 0;
    for(const auto& l : links_) if(l.kind == "manual") ++manualLinkCount;
    out << "MANUAL_LINK_COUNT\t" << manualLinkCount << "\n";
    for(const auto& l : links_){
        if(l.kind != "manual") continue;
        out << "MANUAL_LINK\t" << esc_snapshot(l.from) << "\t" << esc_snapshot(l.to)
            << "\t" << std::setprecision(17) << l.weight << "\t" << esc_snapshot(l.kind) << "\n";
    }

    out.flush();
    if(!out.good()){
        out.close();
        fs::remove(temporary, ec);
        return "ERR SAVE_DB write failed: " + path;
    }
    out.close();

    // Replace only after a fully written snapshot exists. This prevents a crash
    // or power loss from truncating the last known-good database backup.
    ec.clear();
    if(!replace_snapshot_file(temporary, target, ec)){
        std::error_code cleanupEc;
        fs::remove(temporary, cleanupEc);
        return "ERR SAVE_DB atomic replace failed: " + path + " code=" + std::to_string(ec.value());
    }

    return "OK SAVE_DB path=" + path + " format=V2 docs=" + std::to_string(docs_.size()) +
           " segments=" + std::to_string(segments_.size()) + " nodes=" + std::to_string(nodes_.size()) +
           " manual_nodes=" + std::to_string(manualNodes_.size()) +
           " manual_links=" + std::to_string(manualLinkCount) +
           " media=" + std::to_string(media_.size());
}

std::string MyceliaEngine::load_db(const std::string& path){
    if(!snapshot_path_allowed(path)) return "ERR LOAD_DB path denied";
    std::ifstream in(path, std::ios::binary);
    if(!in) return "ERR LOAD_DB cannot read: " + path;
    std::string line;
    if(!std::getline(in,line)) return "ERR LOAD_DB invalid snapshot: " + path;
    const auto magic = trim2(line);
    const bool v1 = magic == "MYCELIADB_SNAPSHOT_V1";
    const bool v2 = magic == "MYCELIADB_SNAPSHOT_V2";
    if(!v1 && !v2) return "ERR LOAD_DB invalid snapshot: " + path;

    std::vector<DocumentCell> docs;
    std::vector<MediaAsset> mediaRows;
    std::unordered_map<std::string,Node> manualNodes;
    std::vector<Link> manualLinks;

    while(std::getline(in,line)){
        if(line.rfind("DOC\t",0)==0){
            auto parts=split_tab_preserve(line);
            if(parts.size()<5) continue;
            DocumentCell d;
            d.id=unesc_snapshot(parts[1]);
            d.path=unesc_snapshot(parts[2]);
            d.type=unesc_snapshot(parts[3]);
            d.text=unesc_snapshot(parts[4]);
            if(parts.size()>5) d.mediaId=unesc_snapshot(parts[5]);
            docs.push_back(std::move(d));
        } else if(line.rfind("MEDIA\t",0)==0){
            auto parts=split_tab_preserve(line);
            if(parts.size()<8) continue;
            MediaAsset m;
            m.id=unesc_snapshot(parts[1]);
            m.sourcePath=unesc_snapshot(parts[2]);
            m.storedPath=unesc_snapshot(parts[3]);
            m.mime=unesc_snapshot(parts[4]);
            m.sha=unesc_snapshot(parts[5]);
            m.documentId=unesc_snapshot(parts[6]);
            try{ m.bytes=(uintmax_t)std::stoull(parts[7]); }catch(...){ m.bytes=0; }
            mediaRows.push_back(std::move(m));
        } else if(v2 && line.rfind("MANUAL_NODE\t",0)==0){
            auto parts=split_tab_preserve(line);
            if(parts.size()<3) continue;
            Node n;
            n.id=unesc_snapshot(parts[1]);
            try{ n.energy=std::stod(parts[2]); }catch(...){ n.energy=0.0; }
            manualNodes[n.id]=std::move(n);
        } else if(v2 && line.rfind("PROP\t",0)==0){
            auto parts=split_tab_preserve(line);
            if(parts.size()<4) continue;
            const auto id=unesc_snapshot(parts[1]);
            auto& n=manualNodes[id];
            if(n.id.empty()) n.id=id;
            n.props[unesc_snapshot(parts[2])]=unesc_snapshot(parts[3]);
        } else if(v2 && line.rfind("MANUAL_LINK\t",0)==0){
            auto parts=split_tab_preserve(line);
            if(parts.size()<5) continue;
            Link l;
            l.from=unesc_snapshot(parts[1]);
            l.to=unesc_snapshot(parts[2]);
            try{ l.weight=std::stod(parts[3]); }catch(...){ l.weight=1.0; }
            l.kind=unesc_snapshot(parts[4]);
            if(l.kind.empty()) l.kind="manual";
            manualLinks.push_back(std::move(l));
        }
    }

    clear_all();
    for(auto& m:mediaRows) media_[m.id]=m;
    for(auto& d: docs) index_document(std::move(d));
    for(auto& [mid,m]: media_){
        add_node(mid,"image_media",fs::path(m.sourcePath).filename().string());
        nodes_[mid].props["mime"]=m.mime;
        nodes_[mid].props["stored"]=m.storedPath;
        nodes_[mid].props["source"]=m.sourcePath;
        nodes_[mid].props["sha"]=m.sha;
        if(!m.documentId.empty() && docs_.contains(m.documentId)){
            add_link(m.documentId,mid,0.99,"derived_from_image");
            add_link(mid,m.documentId,0.99,"source_for_ocr_document");
            for(const auto& sid: docs_[m.documentId].segmentIds) add_link(sid,mid,0.70,"evidenced_by_image");
        }
    }

    if(v2){
        // Restore manual nodes only after all derived nodes have been rebuilt.
        // If an ID collides, the explicit manual node wins because it represents
        // operator-controlled state and was part of the signed/encrypted CMS data model.
        for(auto& [id,n] : manualNodes){
            nodes_[id]=std::move(n);
            manualNodes_.insert(id);
        }
        for(const auto& l : manualLinks){
            if(nodes_.contains(l.from) && nodes_.contains(l.to))
                add_link(l.from,l.to,l.weight,l.kind);
        }
    }

    return "OK LOAD_DB path=" + path + " format=" + std::string(v2?"V2":"V1") +
           " docs=" + std::to_string(docs_.size()) +
           " nodes=" + std::to_string(nodes_.size()) +
           " manual_nodes=" + std::to_string(manualNodes_.size()) +
           " links=" + std::to_string(links_.size()) +
           " media=" + std::to_string(media_.size());
}

std::string MyceliaEngine::execute(const std::string& line){auto c=parse_command(line); std::lock_guard<std::mutex> lock(mu_); std::ostringstream out; try{switch(c.op){
case Op::Ping:return"PONG MyceliaDB Enterprise Native Protocol snapshot=V2 manual_nodes=1 erase_node=1";
case Op::Spawn: if(c.args.empty())return"ERR SPAWN requires <id>"; add_node(c.args[0],"manual",c.args[0]); manualNodes_.insert(c.args[0]); return"OK NODE "+c.args[0];
case Op::Link: if(c.args.size()<2)return"ERR LINK requires <from> <to> [weight]"; if(!nodes_.contains(c.args[0])||!nodes_.contains(c.args[1]))return"ERR missing node"; add_link(c.args[0],c.args[1],c.args.size()>2?std::stod(c.args[2]):1.0,"manual"); return"OK LINK "+c.args[0]+" -> "+c.args[1];
case Op::Mutate: if(c.args.size()<3)return"ERR MUTATE requires <id> <key> <value>"; if(!nodes_.contains(c.args[0]))return"ERR missing node"; nodes_[c.args[0]].props[c.args[1]]=join(c.args,2); return"OK MUTATED "+c.args[0];
case Op::EraseNode: {
    if(c.args.empty()) return "ERR ERASE_NODE requires <id>";
    const auto& id=c.args[0];
    if(!nodes_.contains(id)) return "ERR missing node";
    if(!manualNodes_.contains(id)) return "ERR ERASE_NODE only manual nodes may be erased";
    links_.erase(std::remove_if(links_.begin(),links_.end(),[&](const Link& l){return l.from==id||l.to==id;}),links_.end());
    nodes_.erase(id);
    manualNodes_.erase(id);
    adjacency_.clear();
    for(const auto& l:links_) adjacency_[l.from].insert(l.to);
    return "OK ERASED "+id;
}
case Op::Get: if(c.args.empty()||!nodes_.contains(c.args[0]))return"ERR missing node"; out<<"NODE "<<c.args[0]<<" energy="<<nodes_[c.args[0]].energy; for(auto&[k,v]:nodes_[c.args[0]].props)out<<" "<<k<<"="<<v; return out.str();
case Op::Pulse: if(c.args.empty()||!nodes_.contains(c.args[0]))return"ERR PULSE requires <id>"; {double en=c.args.size()>1?std::stod(c.args[1]):1.0; nodes_[c.args[0]].energy+=en; for(auto&l:links_)if(l.from==c.args[0]&&nodes_.contains(l.to))nodes_[l.to].energy+=en*l.weight;} return"OK PULSE propagated";
case Op::Trace:{ if(c.args.empty()||!nodes_.contains(c.args[0]))return"ERR TRACE requires existing <id>"; int dep=c.args.size()>1?std::stoi(c.args[1]):2; std::queue<std::pair<std::string,int>>q; std::unordered_set<std::string> seen; q.push({c.args[0],0}); seen.insert(c.args[0]); out<<"TRACE"; while(!q.empty()){auto[id,d]=q.front();q.pop();out<<" "<<id; if(d>=dep)continue; auto ai=adjacency_.find(id); if(ai!=adjacency_.end())for(auto&to:ai->second)if(!seen.contains(to)){seen.insert(to);q.push({to,d+1});}} return out.str();}
case Op::ListNodes: out<<"NODES"; for(auto&[id,n]:nodes_)out<<" "<<id; return out.str();
case Op::ListLinks: out<<"LINKS"; for(auto&l:links_)out<<" "<<l.from<<"->"<<l.to<<"("<<std::fixed<<std::setprecision(2)<<l.weight<<":"<<l.kind<<")"; return out.str();
case Op::ImportText: case Op::IngestText: if(c.args.empty())return"ERR INGEST_TEXT requires <path>"; return ingest_text_file(c.args[0],c.args.size()>1?c.args[1]:"","text");
case Op::ImportSql: case Op::IngestSql: if(c.args.empty())return"ERR INGEST_SQL requires <path>"; return ingest_sql_dump(c.args[0],c.args.size()>1?c.args[1]:"");
case Op::IngestOcrImage: if(c.args.empty())return"ERR INGEST_OCR_IMAGE requires <image_path>"; return ingest_ocr_image(c.args[0],c.args.size()>1?c.args[1]:"");
case Op::OcrStatus: return ocr_status();
case Op::ListDocs:return list_docs(); case Op::Search: case Op::QueryField:return query_field(c.args,false); case Op::ExplainResonance:return query_field(c.args,true);
case Op::GetDoc: if(c.args.empty())return"ERR GET_DOC requires <doc_id>"; return get_doc(c.args[0]); case Op::GetNeighbors: if(c.args.empty())return"ERR GET_NEIGHBORS requires <node_id>"; return get_neighbors(c.args[0]);
case Op::FieldStatus:return field_status();
case Op::SaveDb: if(c.args.empty())return"ERR SAVE_DB requires <path>"; return save_db(c.args[0]);
case Op::LoadDb: if(c.args.empty())return"ERR LOAD_DB requires <path>"; return load_db(c.args[0]);
case Op::ClearDb: clear_all(); return "OK CLEAR_DB docs=0 nodes=0 links=0 media=0";
case Op::GetMediaForNode: if(c.args.empty())return"ERR GET_MEDIA_FOR_NODE requires <node_or_segment_id>"; return get_media_for_node(c.args[0]);
case Op::GetMediaForSegment: if(c.args.empty())return"ERR GET_MEDIA_FOR_SEGMENT requires <segment_id>"; return get_media_for_node(c.args[0]);
case Op::GetImageInfo: if(c.args.empty())return"ERR GET_IMAGE_INFO requires <media_id>"; return get_image_info(c.args[0]);
case Op::GpuStatus:return gpu_.status(); case Op::Help:return help(); default:return"ERR unknown command. "+help();}}catch(const std::exception&e){return std::string("ERR exception: ")+e.what();}}
}