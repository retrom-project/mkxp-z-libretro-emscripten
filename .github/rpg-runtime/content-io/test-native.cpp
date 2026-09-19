#include "retrom-content-bridge.h"
#include <emscripten.h>
#include <emscripten/threading.h>
#include <cassert>
#include <cerrno>
#include <cstdio>
#include <cstring>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#include <vector>
static const char* game="11111111-1111-4111-8111-111111111111";
static const char* rtp="22222222-2222-4222-8222-222222222222";
static uint8_t byteAt(uint64_t n) {return (n%251+17*((n/251)%251)+31*((n/65536)%251)+17)%256;}
static void traceReads(int gameFd, int rtpFd) {
  uint32_t seed=0x1234abcd;
  auto next=[&seed]() {seed=seed*1664525u+1013904223u;return seed;};
  uint8_t output[8192];
  for(unsigned index=0;index<10000;++index) {
    unsigned length=1+next()%sizeof(output);
    uint64_t offset=next()%(index%16==0 ? 20*1024*1024-length : 1024*1024);
    int fd=index%2==0 ? gameFd : rtpFd;
    assert(pread(fd,output,length,offset)==static_cast<ssize_t>(length));
    for(unsigned i=0;i<length;++i)assert(output[i]==byteAt(offset+i));
    memset(output,0xff,length);
    if((index+1)%250==0)printf("CONTENT_TRACE:%u\n",index+1);
  }
  puts("CONTENT_TRACE_OK");
}
int main() {
  assert(!emscripten_is_main_browser_thread());
  printf("CONTENT_NATIVE_THREAD:%lu\n",(unsigned long)pthread_self());
  FILE* file=fopen("/manifest","wb");assert(file);
  fprintf(file,"RETROM_CONTENT_IO_V1\n%s\t5368709243\t/game/game.mkxpz\n%s\t5368709243\t/rtp/日本語.zip\n",game,rtp);fclose(file);
  assert(retrom_content_mount_manifest("/manifest","/content")==0);
  struct stat info;assert(stat("/game/game.mkxpz",&info)==0 && info.st_size==5368709243LL);
  assert(stat("/rtp/日本語.zip",&info)==0 && info.st_size==5368709243LL);
  puts("CONTENT_STAT_OK");
  int fd=open("/game/game.mkxpz",O_RDONLY);assert(fd>=0);
  uint8_t bytes[32];assert(pread(fd,bytes,sizeof(bytes),4294967327LL)==32);
  for(unsigned i=0;i<32;++i)assert(bytes[i]==byteAt(4294967327ULL+i));
  assert(lseek(fd,5368709238LL,SEEK_SET)==5368709238LL);assert(read(fd,bytes,32)==5);assert(read(fd,bytes,32)==0);
  int rtpFd=open("/rtp/日本語.zip",O_RDONLY);assert(rtpFd>=0);assert(pread(rtpFd,bytes,32,262140)==32);
  for(unsigned i=0;i<32;++i)assert(bytes[i]==byteAt(262140+i));
  std::vector<uint8_t> large(17*1024*1024);assert(pread(fd,large.data(),large.size(),1024*1024)==static_cast<ssize_t>(large.size()));
  for(size_t i=0;i<large.size();i+=262143)assert(large[i]==byteAt(1024*1024+i));
  traceReads(fd,rtpFd);
  assert(open("/game/game.mkxpz",O_WRONLY)<0 && errno==EROFS);
  assert(open("/game/game.mkxpz",O_WRONLY|O_TRUNC)<0 && errno==EROFS);
  memset(bytes,0x55,sizeof(bytes));
  assert(retrom_content_read_bridge(game,128,0,8,40,(uintptr_t)bytes)==-ETIMEDOUT);
  emscripten_thread_sleep(150);
  for(auto byte:bytes)assert(byte==0x55);
  assert(retrom_content_read_bridge(game,256,0,8,500,(uintptr_t)bytes)==-ECANCELED);
  assert(retrom_content_read_bridge(game,0,0,0,500,(uintptr_t)bytes)==-ECANCELED);
  close(fd);close(rtpFd);puts("CONTENT_FIXTURE_OK");
  return 0;
}
