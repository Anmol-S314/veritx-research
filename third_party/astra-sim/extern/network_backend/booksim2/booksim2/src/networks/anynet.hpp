// $Id$

/*
 Copyright (c) 2007-2015, Trustees of The Leland Stanford Junior University
 All rights reserved.

 Redistribution and use in source and binary forms, with or without
 modification, are permitted provided that the following conditions are met:

 Redistributions of source code must retain the above copyright notice, this 
 list of conditions and the following disclaimer.
 Redistributions in binary form must reproduce the above copyright notice, this
 list of conditions and the following disclaimer in the documentation and/or
 other materials provided with the distribution.

 THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
 ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
 WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE 
 DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR
 ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
 (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
 LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON
 ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
 (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
 SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
*/

#ifndef _ANYNET_HPP_
#define _ANYNET_HPP_

#include "network.hpp"
#include "routefunc.hpp"
#include <cassert>
#include <string>
#include <map>
#include <list>

// One declared channel between an adjacent pair. `latency` is the wire
// delay; `cost` is what routing minimises. They are separate so a slow
// link does not silently become a non-preferred path: the file may give an
// explicit cost token, and when it does not the cost defaults to the
// latency (the historic single-number semantics). Repeated declarations of
// the same pair are PARALLEL LANES, not duplicates to overwrite.
struct AnyNetEdge {
  int port;
  int latency;
  int cost;
  AnyNetEdge() : port(-1), latency(1), cost(-1) {}
};

// One first-hop decision for a destination node. `lane_base`+`lane_count`
// describe parallel lanes between the same pair (a packet is pinned to one
// lane by its pid, so lanes raise aggregate bandwidth without reordering a
// packet). `drop` is the tap index when the first hop is a shared
// MultiDropChannel, else -1.
struct AnyNetRoute {
  int port;
  int drop;
  int lane_base;
  int lane_count;
  AnyNetRoute() : port(-1), drop(-1), lane_base(-1), lane_count(1) {}
};

// One shared, tapped wire: a single driver feeds many taps and only one
// flit can be on it per cycle (that single slot IS the bus contention
// model). Reuses MultiDropChannel, whose drop index is the tap's position
// in `taps` (taps are registered in this order at build time).
struct AnyNetMultiDrop {
  vector<int> taps;
  int latency;
  int cost;
  int out_port;
  AnyNetMultiDrop() : latency(1), cost(-1), out_port(-1) {}
};

class AnyNet : public Network {

  string file_name;
  //associtation between  nodes and routers
  map<int, int > node_list;
  //[link type][src router][dest] = declared lanes (one entry per clause)
  vector<map<int,  map<int, vector<AnyNetEdge> > > > router_list;
  //stores minimal routing information from every router to every node
  //[router][dest_node]=(port, drop, lane_base, lane_count)
  vector<map<int, AnyNetRoute> > routing_table;
  //[driver router] = shared/tapped wires it drives (multidrop lines)
  map<int, vector<AnyNetMultiDrop> > md_list;
  // VeritX (B3.7b): certified route evidence. When routing_dump_file is
  // non-empty the built all-pairs first-hop table is written there, so a
  // certified runner can compare the EXECUTED route realization against
  // the authoritative RouteArtifact instead of trusting the routing
  // function name. Diagnostics only: never changes routing behavior.
  string routing_dump_file;
  // [src router][dest node] = next router toward that node (== src router
  // when the destination node is local to the source router).
  vector<map<int, int> > routing_next;

  void _ComputeSize( const Configuration &config );
  void _BuildNet( const Configuration &config );
  void readFile();
  void buildRoutingTable();
  void route(int r_start);

public:
  AnyNet( const Configuration &config, const string & name );
  ~AnyNet();

  int GetN( ) const{ return -1;}
  int GetK( ) const{ return -1;}

  static void RegisterRoutingFunctions();
  double Capacity( ) const {return -1;}
  void InsertRandomFaults( const Configuration &config ){}
};

void min_anynet( const Router *r, const Flit *f, int in_channel, 
		      OutputSet *outputs, bool inject );
#endif
