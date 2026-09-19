#include "retrom-content-bridge.h"
#include <emscripten.h>
#include <emscripten/wasmfs.h>
#include <cerrno>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <mutex>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>
#include <sys/stat.h>
#include <unistd.h>
namespace {
std::mutex metadataMutex;
std::unordered_map<std::string, uint64_t> sizes;
struct Entry {std::string id, path; uint64_t size;};
bool uuid(const std::string& id) {
  if (id.size() != 36) {return false;}
  for (size_t i=0;i<id.size();++i) {
    if (i==8 || i==13 || i==18 || i==23) {if(id[i]!='-') return false;}
    else if (!(id[i]>='0' && id[i]<='9') && !(id[i]>='a' && id[i]<='f')) return false;
  }
  return true;
}
bool utf8(const std::string& s) {
  for (size_t i=0;i<s.size();) {
    unsigned c=static_cast<unsigned char>(s[i++]);
    if (c<128) {if(c<32 || c==127) return false; continue;}
    unsigned n=c>=0xc2 && c<=0xdf?1:c>=0xe0 && c<=0xef?2:c>=0xf0 && c<=0xf4?3:0;
    if (!n || i+n>s.size()) return false;
    unsigned cp=c&((1u<<(6-n))-1), min=n==1?0x80:n==2?0x800:0x10000;
    for (unsigned j=0;j<n;++j) {unsigned next=static_cast<unsigned char>(s[i++]);if((next&0xc0)!=0x80)return false;cp=(cp<<6)|(next&63);}
    if (cp<min || cp>0x10ffff || (cp>=0xd800 && cp<=0xdfff)) return false;
  }
  return true;
}
bool pathValid(const std::string& path) {
  if(path.size()<2 || path.size()>1024 || path.front()!='/' || path.back()=='/' || !utf8(path) || path.find('\\')!=std::string::npos) return false;
  size_t at=1;
  while(at<path.size()) {auto end=path.find('/',at);auto part=path.substr(at,end-at);if(part.empty() || part=="." || part=="..") return false;if(end==std::string::npos)break;at=end+1;}
  return true;
}
bool decimal(const std::string& text, uint64_t& size) {
  if(text.empty() || text.size()>16 || (text.size()>1 && text[0]=='0'))return false;
  size=0;for(char c:text) {if(c<'0'||c>'9')return false;size=size*10+c-'0';if(size>9007199254740991ULL)return false;}
  return true;
}
bool parents(const std::string& path) {
  for (size_t at=1;(at=path.find('/',at))!=std::string::npos;++at) {
    if(mkdir(path.substr(0,at).c_str(),0777)!=0 && errno!=EEXIST)return false;
  }
  return true;
}
}
extern "C" EMSCRIPTEN_KEEPALIVE double retrom_content_get_size(const char* fileId) {
  if(!fileId)return -1;
  std::lock_guard<std::mutex> lock(metadataMutex);
  auto it=sizes.find(fileId);return it==sizes.end()?-1:static_cast<double>(it->second);
}
extern "C" int retrom_content_mount_manifest(const char* manifestPath, const char* mountPath) {
  if(!manifestPath || !mountPath || !pathValid(mountPath))return -EINVAL;
  FILE* input=fopen(manifestPath,"rb");if(!input)return -ENOENT;
  char* line=nullptr;size_t capacity=0;ssize_t count=getline(&line,&capacity,input);
  // Header length is checked from the actual read, never getline capacity.
  bool valid=count==static_cast<ssize_t>(strlen("RETROM_CONTENT_IO_V1\n")) && std::string(line,count)=="RETROM_CONTENT_IO_V1\n";
  std::vector<Entry> entries;std::unordered_set<std::string> ids,paths;
  while(valid && (count=getline(&line,&capacity,input))!=-1) {
    if(count<1 || count>1200 || line[count-1]!='\n' || entries.size()>=128) {valid=false;break;}
    std::string row(line,count-1);auto a=row.find('\t'),b=row.find('\t',a==std::string::npos?row.size():a+1);
    if(a==std::string::npos || b==std::string::npos || row.find('\t',b+1)!=std::string::npos) {valid=false;break;}
    Entry entry{row.substr(0,a),row.substr(b+1),0};
    if(!uuid(entry.id) || !decimal(row.substr(a+1,b-a-1),entry.size) || !pathValid(entry.path) ||
       !ids.insert(entry.id).second || !paths.insert(entry.path).second) {valid=false;break;}
    entries.push_back(entry);
  }
  if(ferror(input))valid=false;free(line);fclose(input);
  if(!valid || entries.empty())return -EINVAL;
  {std::lock_guard<std::mutex> lock(metadataMutex);if(!sizes.empty())return -EINVAL;for(const auto& entry:entries)sizes.emplace(entry.id,entry.size);}
  backend_t backend=wasmfs_create_fetch_backend("",262144);
  if(!backend || !parents(mountPath) || wasmfs_create_directory(mountPath,0555,backend))return -EIO;
  for(const auto& entry:entries) {
    const std::string backing=std::string(mountPath)+"/"+entry.id;
    int fd=wasmfs_create_file(backing.c_str(),0666,backend);if(fd<0)return -EIO;close(fd);
    if(!parents(entry.path) || symlink(backing.c_str(),entry.path.c_str()))return -EIO;
  }
  return 0;
}
