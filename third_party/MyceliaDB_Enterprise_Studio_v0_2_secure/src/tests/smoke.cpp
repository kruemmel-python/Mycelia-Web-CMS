#include "server/MyceliaServer.hpp"
#include "studio/MyceliaClient.hpp"
#include <chrono>
#include <filesystem>
#include <iostream>
#include <thread>
int main(){
    mycelia::MyceliaServer server;
    if(!server.start("127.0.0.1",4555)){std::cerr<<"server failed\n";return 2;}
    std::thread t([&]{server.run();});
    std::this_thread::sleep_for(std::chrono::milliseconds(200));
    mycelia::MyceliaClient c;
    if(!c.connect("127.0.0.1",4555)){std::cerr<<"client failed\n";return 3;}
    auto ping=c.request("PING");
    auto a=c.request("SPAWN alpha");
    auto b=c.request("SPAWN beta");
    auto l=c.request("LINK alpha beta 0.75");
    auto p=c.request("PULSE alpha 10");
    auto tr=c.request("TRACE alpha 3");
    auto gpu=c.request("GPU_STATUS");
    auto ocrs=c.request("OCR_STATUS");
    auto doc=std::filesystem::current_path()/ "examples"/"antrag_peter_mueller_leipzig.txt";
    auto sql=std::filesystem::current_path()/ "examples"/"demo_dump.sql";
    auto im=c.request(std::string("INGEST_TEXT \"")+doc.string()+"\" \"doc:test_antrag\"");
    auto is=c.request(std::string("INGEST_SQL \"")+sql.string()+"\" \"sql:test_dump\"");
    auto fs=c.request("FIELD_STATUS");
    auto docs=c.request("LIST_DOCS");
    auto sr=c.request("QUERY_FIELD \"Peter Müller Leipzig\"");
    auto ex=c.request("EXPLAIN_RESONANCE \"Peter Müller Leipzig\"");
    std::cout<<ping<<"\n"<<a<<"\n"<<b<<"\n"<<l<<"\n"<<p<<"\n"<<tr<<"\n"<<gpu<<"\n"<<ocrs<<"\n"<<im<<"\n"<<is<<"\n"<<fs<<"\n"<<docs<<"\n"<<sr<<"\n"<<ex<<"\n";
    bool ok=ping.rfind("PONG",0)==0&&a.rfind("OK",0)==0&&b.rfind("OK",0)==0&&l.rfind("OK",0)==0&&p.rfind("OK",0)==0&&tr.find("beta")!=std::string::npos&&im.rfind("OK",0)==0&&is.rfind("OK",0)==0&&fs.find("segments=")!=std::string::npos&&sr.find("RESONANCE_RESULTS")!=std::string::npos&&ex.find("energy_diffusion")!=std::string::npos&&ocrs.find("OCR_STATUS")!=std::string::npos;
    c.close(); server.stop();
#ifndef _WIN32
    pthread_cancel(t.native_handle());
#endif
    if(t.joinable())t.detach();
    if(ok){std::cout<<"SMOKE OK: true Mycelia resonance engine, document ingest, OCR bridge, energetic query and GPU bridge communicate.\n";return 0;}
    std::cerr<<"SMOKE FAILED\n";return 1;
}