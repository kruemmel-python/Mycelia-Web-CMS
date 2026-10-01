#pragma once
#include "common/Protocol.hpp"
#include "common/GpuDriver.hpp"
#include <mutex>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

namespace mycelia {
struct Node { std::string id; std::unordered_map<std::string,std::string> props; double energy{0.0}; };
struct Link { std::string from; std::string to; double weight{1.0}; std::string kind{"mycelial"}; };
struct SegmentCell { std::string id, documentId, title, text; };
struct DocumentCell { std::string id, path, type{"text"}, text; std::unordered_map<std::string,int> termFrequency; std::vector<std::string> segmentIds; std::string mediaId; };
struct MediaAsset { std::string id, sourcePath, storedPath, mime, sha, documentId; uintmax_t bytes{0}; };

class MyceliaEngine {
public:
    MyceliaEngine();
    std::string execute(const std::string& line);
private:
    std::mutex mu_;
    std::unordered_map<std::string,Node> nodes_;
    std::vector<Link> links_;
    std::unordered_set<std::string> manualNodes_;
    std::unordered_map<std::string,DocumentCell> docs_;
    std::unordered_map<std::string,SegmentCell> segments_;
    std::unordered_map<std::string,MediaAsset> media_;
    std::unordered_map<std::string,std::unordered_set<std::string>> inverted_;
    std::unordered_map<std::string,std::unordered_set<std::string>> segmentIndex_;
    std::unordered_map<std::string,std::unordered_set<std::string>> adjacency_;
    GpuDriver gpu_;
    std::string help() const;
    void add_node(const std::string& id,const std::string& kind,const std::string& label);
    void add_link(const std::string& from,const std::string& to,double weight,const std::string& kind);
    void index_document(DocumentCell doc);
    std::string ingest_text_file(const std::string& path,const std::string& explicitId,const std::string& type);
    std::string ingest_sql_dump(const std::string& path,const std::string& explicitId);
    std::string ingest_ocr_image(const std::string& path,const std::string& explicitId);
    std::string ocr_status() const;
    std::string list_docs() const;
    std::string get_doc(const std::string& id) const;
    std::string query_field(const std::vector<std::string>& args,bool explain) const;
    std::string get_neighbors(const std::string& id) const;
    std::string get_media_for_node(const std::string& id) const;
    std::string get_image_info(const std::string& id) const;
    std::string field_status() const;
    std::string save_db(const std::string& path) const;
    std::string load_db(const std::string& path);
    void clear_all();
};
}