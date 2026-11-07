#include <verilated.h>
#include "Vring_native_fabric.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <random>
#include <vector>

static constexpr int N=64, TOTAL=N*N;
struct Packet { int src,dst,id; uint32_t data; };
int main(int argc,char**argv){
  Verilated::commandArgs(argc,argv);
  Vring_native_fabric d;
  std::vector<Packet> packets; int id=1;
  for(int s=0;s<N;s++) for(int t=0;t<N;t++) if(s!=t) packets.push_back({s,t,id++,uint32_t((s<<16)|t)});
  // Include each node's local-ejection packet too.
  for(int s=0;s<N;s++) packets.push_back({s,s,id++,uint32_t((s<<16)|s)});
  std::array<int,N> accepted{}; std::array<int,N> delivered{};
  std::mt19937 rng(0x64a11); int next=0, cycles=0, stalled=0;
  d.rst=1; d.inject_valid=0; d.eject_ready=~0ULL;
  auto tick=[&](){d.clk=0;d.eval();d.clk=1;d.eval();}; tick();tick();d.rst=0;
  while((next<(int)packets.size() || std::accumulate(delivered.begin(),delivered.end(),0)<(int)packets.size()) && cycles<200000){
    ++cycles;
    uint64_t val=0,ready=0;
    for(int s=0;s<N;s++) if(accepted[s]<1 && next<(int)packets.size() && packets[next].src==s){
      val|=1ULL<<s;
      auto p=packets[next]; d.inject_dest[s]=p.dst;d.inject_data[s]=p.data;
      int half=(p.src>p.dst); d.inject_vc|=uint64_t(half)<<s;
    }
    // Random backpressure with guaranteed fair service.
    for(int t=0;t<N;t++) if((rng()%5)!=0 || stalled>40) ready|=1ULL<<t;
    d.inject_valid=val;d.eject_ready=ready;d.eval();
    for(int s=0;s<N;s++) if((val>>s&1) && (d.inject_ready>>s&1)){
      accepted[s]++; next++; if(accepted[s]>1) { std::cerr<<"duplicate source send\n"; return 2; }
    }
    for(int t=0;t<N;t++) if((d.eject_valid>>t&1) && (ready>>t&1)){
      uint32_t data=(d.eject_data>>(32*t))&0xffffffffU;
      bool found=false;
      for(auto&p:packets) if(p.dst==t&&p.data==data){found=true;break;}
      if(!found){std::cerr<<"wrong destination/data at "<<t<<"\n";return 3;}
      delivered[t]++;
      if(delivered[t]>N){std::cerr<<"duplicate delivery\n";return 4;}
    }
    bool any=false;for(int t=0;t<N;t++) if(!(ready>>t&1)) any=true;
    stalled=any?stalled+1:0;
    tick();
  }
  int total=std::accumulate(delivered.begin(),delivered.end(),0);
  if(total!=TOTAL||cycles>=200000){std::cerr<<"not drained total="<<total<<" accepted="<<next<<" cycles="<<cycles<<"\n";return 5;}
  std::cout<<"PASS packets="<<total<<" all destinations correct; randomized backpressure; drained cycles="<<cycles<<"\n";
  d.final(); return 0;
}
