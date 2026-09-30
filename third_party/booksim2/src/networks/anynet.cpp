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

/*anynet
 *
 *Network setup file format
 *example 1:
 *router 0 router 1 15 router 2
 *
 *Router 0 is connected to router 1 with a 15-cycle channel, and router 0 is
 * connected to router 2 with a 1-cycle channel. Every clause declares ONLY the
 * direction it names; the reverse channel exists only if it is declared on its
 * own line/clause (which is how a bidirectional link is written). A one-way
 * link is therefore expressible, and stays one-way.
 *example 1b:
 *router 0 router 1 15 1
 *
 *The second number is the routing COST; it defaults to the latency when
 * omitted. Routing minimises cost, so an explicit "15 1" gives a 15-cycle wire
 * that still costs one hop -- a slow link does not silently become a
 * non-preferred path.
 *example 1c:
 *router 0 router 1 4
 *router 0 router 1 4
 *
 *A repeated clause is a PARALLEL LANE, not a duplicate to overwrite. Each lane
 * gets its own output port and credit channel; the router core already pins a
 * packet to the port its head flit chose.
 *example 2:
 *router 0 node 0 node 1 5 node 2 5
 *
 *Router 0 is directly connected to node 0-2. Channel latency is 5cycles for 1 and 2. In 
 * this case the latency specification is bidirectional, the injeciton and ejection lat
 * for node 1 and 2 are 5-cycle
 *
 *other notes:
 *
 *Router and node numbers must be sequential starting with 0
 *Credit channel latency follows the channel latency, even though it travels in revse
 * direction this might not be desired
 *
 */

#include "anynet.hpp"
#include <fstream>
#include <sstream>
#include <limits>
#include <algorithm>
//this is a hack, I can't easily get the routing talbe out of the network
map<int, int>* global_routing_table;

AnyNet::AnyNet( const Configuration &config, const string & name )
  :  Network( config, name ){

  router_list.resize(2);
  _ComputeSize( config );
  _Alloc( );
  _BuildNet( config );
}

AnyNet::~AnyNet(){
  for(int i = 0; i < 2; ++i) {
    for(map<int, map<int, vector<AnyNetEdge> > >::iterator iter = router_list[i].begin();
	iter != router_list[i].end();
	++iter) {
      iter->second.clear();
    }
  }
}

void AnyNet::_ComputeSize( const Configuration &config ){
  file_name = config.GetStr("network_file");
  // VeritX (B3.7b): optional certified route-evidence dump path.
  routing_dump_file = config.GetStr("routing_dump_file");
  if(file_name==""){
    cout<<"No network file name provided"<<endl;
    exit(-1);
  }
  //parse the network description file
  readFile();

  _channels =0;
  cout<<"========================Network File Parsed=================\n";
  cout<<"******************node listing**********************\n";
  map<int,  int >::iterator iter;
  for(iter = node_list.begin(); iter!=node_list.end(); iter++){
    cout<<"Node "<<iter->first;
    cout<<"\tRouter "<<iter->second<<endl;
  }

  map<int,   map<int, vector<AnyNetEdge> > >::iterator iter3;
  cout<<"\n****************router to node listing*************\n";
  for(iter3 = router_list[0].begin(); iter3!=router_list[0].end(); iter3++){
    cout<<"Router "<<iter3->first<<endl;
    map<int, vector<AnyNetEdge> >::iterator iter2;
    for(iter2 = iter3->second.begin(); 
	iter2!=iter3->second.end(); 
	iter2++){
      cout<<"\t Node "<<iter2->first<<" lat "<<iter2->second[0].latency<<endl;
    }
  }

  cout<<"\n*****************router to router listing************\n";
  for(iter3 = router_list[1].begin(); iter3!=router_list[1].end(); iter3++){
    cout<<"Router "<<iter3->first<<endl;
    map<int, vector<AnyNetEdge> >::iterator iter2;
    if(iter3->second.size() == 0){
      cout<<"Caution Router "<<iter3->first
	  <<" is not connected to any other Router\n"<<endl;
    }
    for(iter2 = iter3->second.begin(); 
	iter2!=iter3->second.end(); 
	iter2++){
      cout<<"\t Router "<<iter2->first<<" lat "<<iter2->second[0].latency
	  <<" cost "<<iter2->second[0].cost
	  <<" lanes "<<iter2->second.size()<<endl;
      _channels += iter2->second.size();
    }
  }

  _size = router_list[1].size();
  _nodes = node_list.size();

}



void AnyNet::_BuildNet( const Configuration &config ){
  

  //I need to keep track the output ports for each router during build
  int * outport = (int*)malloc(sizeof(int)*_size);
  for(int i = 0; i<_size; i++){outport[i] = 0;}

  cout<<"==========================Node to Router =====================\n";
  //adding the injection/ejection chanenls first
  map<int,   map<int, vector<AnyNetEdge> > >::iterator niter;
  for(niter = router_list[0].begin(); niter!=router_list[0].end(); niter++){
    map<int,   map<int, vector<AnyNetEdge> > >::iterator riter = router_list[1].find(niter->first);
    int node = niter->first;
    // Out-degree: this router's own declared outgoing lanes.
    int out_degree = 0;
    for(map<int, vector<AnyNetEdge> >::iterator o = riter->second.begin();
	o!=riter->second.end(); o++){
      out_degree += o->second.size();
    }
    // In-degree: every declared lane, from any router, that lands here. A
    // directed (one-way) fabric can have more inputs than outputs, so the
    // two cannot share one radix.
    int in_degree = 0;
    for(int p = 0; p < _size; p++){
      map<int, vector<AnyNetEdge> >::iterator back =
	router_list[1][p].find(node);
      if(back != router_list[1][p].end()){
	in_degree += back->second.size();
      }
    }
    int node_conns = niter->second.size();
    cout<<"router "<<node<<" radix in "<<(node_conns+in_degree)
	<<" out "<<(node_conns+out_degree)<<endl;
    //decalre the routers 
    ostringstream router_name;
    router_name << "router";
    router_name << "_" <<  node ;
    _routers[node] = Router::NewRouter( config, this, router_name.str( ), 
					node, node_conns+in_degree,
					node_conns+out_degree );
    _timed_modules.push_back(_routers[node]);
    //add injeciton ejection channels
    map<int, vector<AnyNetEdge> >::iterator nniter;
    for(nniter = niter->second.begin();nniter!=niter->second.end(); nniter++){
      int link = nniter->first;
      //add the outport port assined to the map
      nniter->second[0].port = outport[node];
      outport[node]++;
      cout<<"\t connected to node "<<link<<" at outport "<<nniter->second[0].port
	  <<" lat "<<nniter->second[0].latency<<endl;
      _inject[link]->SetLatency(nniter->second[0].latency);
      _inject_cred[link]->SetLatency(nniter->second[0].latency);
      _eject[link]->SetLatency(nniter->second[0].latency);
      _eject_cred[link]->SetLatency(nniter->second[0].latency);

      _routers[node]->AddInputChannel( _inject[link], _inject_cred[link] );
      _routers[node]->AddOutputChannel( _eject[link], _eject_cred[link] );
    }

  }

  cout<<"==========================Router to Router =====================\n";
  //add inter router channels
  //since there is no way to systematically number the channels we just start from 0
  //the map, is a mapping of output->input
  int channel_count = 0; 
  for(niter = router_list[0].begin(); niter!=router_list[0].end(); niter++){
    map<int,   map<int, vector<AnyNetEdge> > >::iterator riter = router_list[1].find(niter->first);
    int node = niter->first;
    map<int, vector<AnyNetEdge> >::iterator rriter;
    cout<<"router "<<node<<endl;
    for(rriter = riter->second.begin();rriter!=riter->second.end(); rriter++){
      int other_node = rriter->first;
      // One channel per declared lane: a repeated clause is a parallel lane,
      // and every lane gets its own output port and credit channel.
      for(size_t lane = 0; lane < rriter->second.size(); lane++){
	int link = channel_count;
	//add the outport port assined to the map
	rriter->second[lane].port = outport[node];
	outport[node]++;
	cout<<"\t connected to router "<<other_node<<" using link "<<link
	    <<" at outport "<<rriter->second[lane].port
	    <<" lat "<<rriter->second[lane].latency<<endl;

	_chan[link]->SetLatency(rriter->second[lane].latency);
	_chan_cred[link]->SetLatency(rriter->second[lane].latency);

	_routers[node]->AddOutputChannel( _chan[link], _chan_cred[link] );
	_routers[other_node]->AddInputChannel( _chan[link], _chan_cred[link]);
	channel_count++;
      }
    }
  }

  buildRoutingTable();

}


void AnyNet::RegisterRoutingFunctions() {
  gRoutingFunctionMap["min_anynet"] = &min_anynet;
}

void min_anynet( const Router *r, const Flit *f, int in_channel, 
		 OutputSet *outputs, bool inject ){
  int out_port=-1;
  if(!inject){
    assert(global_routing_table[r->GetID()].count(f->dest)!=0);
    out_port=global_routing_table[r->GetID()][f->dest];
  }
 

  int vcBegin = 0, vcEnd = gNumVCs-1;
  if ( f->type == Flit::READ_REQUEST ) {
    vcBegin = gReadReqBeginVC;
    vcEnd   = gReadReqEndVC;
  } else if ( f->type == Flit::WRITE_REQUEST ) {
    vcBegin = gWriteReqBeginVC;
    vcEnd   = gWriteReqEndVC;
  } else if ( f->type ==  Flit::READ_REPLY ) {
    vcBegin = gReadReplyBeginVC;
    vcEnd   = gReadReplyEndVC;
  } else if ( f->type ==  Flit::WRITE_REPLY ) {
    vcBegin = gWriteReplyBeginVC;
    vcEnd   = gWriteReplyEndVC;
  }

  outputs->Clear( );

  outputs->AddRange( out_port , vcBegin, vcEnd );
}

void AnyNet::buildRoutingTable(){
  cout<<"========================== Routing table  =====================\n";  
  routing_table.resize(_size);
  routing_next.resize(_size);
  for(int i = 0; i<_size; i++){
    route(i);
  }
  global_routing_table = &routing_table[0];

  // VeritX (B3.7b): dump the built all-pairs first-hop table for
  // mechanical comparison against the authoritative RouteArtifact.
  // Format: "src_router <r> dst_node <n> next_router <m> port <p>"
  // (next_router == r means the destination node is local to router r).
  // Purely diagnostic: emitted only when routing_dump_file is set.
  if(!routing_dump_file.empty()){
    ofstream dump(routing_dump_file.c_str());
    if(!dump.is_open()){
      cout<<"AnyNet: cannot open routing_dump_file "<<routing_dump_file<<endl;
      exit(-1);
    }
    dump<<"# VeritX anynet routing table dump (executed first-hop realization)\n";
    for(int r = 0; r<_size; r++){
      map<int, int>::iterator iter;
      for(iter = routing_next[r].begin(); iter != routing_next[r].end(); iter++){
        dump<<"src_router "<<r<<" dst_node "<<iter->first
            <<" next_router "<<iter->second
            <<" port "<<routing_table[r][iter->first]<<"\n";
      }
    }
    dump.close();
  }
}


//11/7/2012
//basically djistra's, tested on a large dragonfly anynet configuration
void AnyNet::route(int r_start){
  int* dist = new int[_size];
  int* prev = new int[_size];
  set<int> rlist;
  for(int i = 0; i<_size; i++){
    dist[i] =  numeric_limits<int>::max();
    prev[i] = -1;
    rlist.insert(i);
  }
  dist[r_start] = 0;
  while(!rlist.empty()){
    //find min 
    int min_dist = numeric_limits<int>::max();
    int min_cand = -1;
    for(set<int>::iterator i = rlist.begin();
	i!=rlist.end();
	i++){
      if(dist[*i]<min_dist){
	min_dist = dist[*i];
	min_cand = *i;
      }
    }
    if(min_cand == -1){
      // VeritX: a router unreachable from r_start leaves the all-pairs table
      // undefined; erase(-1) is a no-op and this loop would spin forever.
      // Refuse loudly rather than hang the benchmark binary.
      cerr << "Anynet: router " << r_start << " cannot reach every router "
	   << "(directed graph is not strongly connected) -- refusing to "
	   << "build a partial routing table" << endl;
      exit(-1);
    }
    rlist.erase(min_cand);

    //neighbor: routing minimises COST, which is the link's own cost token
    //(default: its latency). Latency stays a pure wire delay.
    for(map<int,vector<AnyNetEdge> >::iterator i = router_list[1][min_cand].begin();
	i!=router_list[1][min_cand].end(); 
	i++){
      int new_dist = dist[min_cand] + i->second[0].cost;
      if(new_dist < dist[i->first]){
	dist[i->first] = new_dist;
	prev[i->first] = min_cand;
      }
    }
  }
  
  //post process from the prev list
  for(int i = 0; i<_size; i++){
    if(prev[i] ==-1){ //self
      assert(i == r_start);
      for(map<int, vector<AnyNetEdge> >::iterator iter = router_list[0][i].begin();
	  iter!=router_list[0][i].end();
	  iter++){
	routing_table[r_start][iter->first]=iter->second[0].port;
	// VeritX (B3.7b): destination local to r_start -> next hop is self.
	routing_next[r_start][iter->first]=r_start;
	//cout<<"node "<<iter->first<<" port "<< iter->second.first<<endl;
      }
    } else {
      int distance=0;
      int neighbor=i;
      while(prev[neighbor]!=r_start){
	assert(router_list[1][neighbor].count(prev[neighbor])>0);
	distance+=router_list[1][prev[neighbor]][neighbor][0].latency;//REVERSE lat
	neighbor= prev[neighbor];
      }
      distance+=router_list[1][prev[neighbor]][neighbor][0].latency;//lat

      assert( router_list[1][r_start].count(neighbor)!=0);
      int port = router_list[1][r_start][neighbor][0].port;
      for(map<int, vector<AnyNetEdge> >::iterator iter = router_list[0][i].begin();
	  iter!=router_list[0][i].end();
	  iter++){
	routing_table[r_start][iter->first]=port;
	// VeritX (B3.7b): first router after r_start toward destination i.
	routing_next[r_start][iter->first]=neighbor;
	//cout<<"node "<<iter->first<<" port "<< port<<" dist "<<distance<<endl;
      }
    }
  }
}


void AnyNet::readFile(){

  ifstream network_list;
  string line;
  enum ParseState{HEAD_TYPE=0,
		  HEAD_ID,
		  BODY_TYPE, 
		  BODY_ID,
		  LINK_WEIGHT,
		  LINK_COST};
  enum ParseType{NODE=0,
		 ROUTER,
		 UNKNOWN};

  network_list.open(file_name.c_str());
  if(!network_list.is_open()){
    cout<<"Anynet:can't open network file "<<file_name<<endl;
    exit(-1);
  }
  
  //loop through the entire file
  while(!network_list.eof()){
    getline(network_list,line);
    if(line==""){
      continue;
    }

    ParseState state=HEAD_TYPE;
    //position to parse out white sspace
    int pos = 0;
    int next_pos=-1;
    string temp;
    //the first node and its type
    int head_id = -1;
    ParseType head_type = UNKNOWN;
    //stuff that head are linked to
    ParseType body_type = UNKNOWN;
    int body_id = -1;
    //the lanes of the clause currently being parsed (a repeated clause is
    //a parallel lane; the last-appended lane takes this clause's tokens)
    vector<AnyNetEdge>* cur_lanes = NULL;

    do{

      //skip empty spaces
      next_pos = line.find(" ",pos);
      temp = line.substr(pos,next_pos-pos);
      pos = next_pos+1;
      if(temp=="" || temp==" "){
	continue;
      }

      switch(state){
      case HEAD_TYPE:
	if(temp=="router"){
	  head_type = ROUTER;
	} else if (temp == "node"){
	  head_type = NODE;
	} else {
	  cout<<"Anynet:Unknow head of line type "<<temp<<"\n";
	  assert(false);
	}
	state=HEAD_ID;
	break;
      case HEAD_ID:
	//need better error check
	head_id = atoi(temp.c_str());

	//intialize router structures
	if(router_list[NODE].count(head_id) == 0){
	  router_list[NODE][head_id] = map<int, vector<AnyNetEdge> >();
	}
	if(router_list[ROUTER].count(head_id) == 0){
	  router_list[ROUTER][head_id] = map<int, vector<AnyNetEdge> >();
	}  

	state=BODY_TYPE;
	break;
      case LINK_WEIGHT:
	if(temp=="router"||
	   temp == "node"){
	  //ignore: no latency token, the default stands
	} else {
	  // Latency is the wire delay. It does NOT by itself become the
	  // routing metric; an optional following token sets the cost.
	  int link_latency= atoi(temp.c_str());
	  if(cur_lanes != NULL && !cur_lanes->empty()){
	    cur_lanes->back().latency = link_latency;
	  }
	  state=LINK_COST;
	  break;
	}
	//intentionally letting it flow through
      case LINK_COST:
	if(temp=="router"||
	   temp == "node"){
	  //ignore: no cost token, cost defaults to the latency
	} else {
	  int link_cost= atoi(temp.c_str());
	  if(cur_lanes != NULL && !cur_lanes->empty()){
	    cur_lanes->back().cost = link_cost;
	  }
	  state=BODY_TYPE;
	  break;
	}
	//intentionally letting it flow through
      case BODY_TYPE:
	if(temp=="router"){
	  body_type = ROUTER;
	} else if (temp == "node"){
	  body_type = NODE;
	} else {
	  cout<<"Anynet:Unknow body type "<<temp<<"\n";
	  assert(false);
	}
	state=BODY_ID;
	break;
      case BODY_ID:
	body_id = atoi(temp.c_str());	
	//intialize router structures if necessary
	if(body_type==ROUTER){
	  if(router_list[NODE].count(body_id) ==0){
	    router_list[NODE][body_id] = map<int, vector<AnyNetEdge> >();
	  }
	  if(router_list[ROUTER].count(body_id) == 0){
	    router_list[ROUTER][body_id] = map<int, vector<AnyNetEdge> >();
	  }
	}

	if(head_type==NODE && body_type==NODE){ 

	  cout<<"Anynet:Cannot connect node to node "<<temp<<"\n";
	  assert(false);

	} else if(head_type==NODE && body_type==ROUTER){

	  if(node_list.count(head_id)!=0 &&
	     node_list[head_id]!=body_id){
	    cout<<"Anynet:Node "<<body_id<<" trying to connect to multiple router "
		<<body_id<<" and "<<node_list[head_id]<<endl;
	    assert(false);
	  }
	  node_list[head_id]=body_id;
	  if(router_list[NODE][body_id].count(head_id)==0){
	    router_list[NODE][body_id][head_id]=vector<AnyNetEdge>(1);
	  }
	  cur_lanes = &router_list[NODE][body_id][head_id];

	} else if(head_type==ROUTER && body_type==NODE){
	  //insert and check node
	  if(node_list.count(body_id) != 0 &&
	     node_list[body_id]!=head_id){
	    cout<<"Anynet:Node "<<body_id<<" trying to connect to multiple router "
		<<body_id<<" and "<<node_list[head_id]<<endl;
	    assert(false);
	  }
	  node_list[body_id] = head_id;
	  if(router_list[NODE][head_id].count(body_id)==0){
	    router_list[NODE][head_id][body_id]=vector<AnyNetEdge>(1);
	  }
	  cur_lanes = &router_list[NODE][head_id][body_id];

	} else if(head_type==ROUTER && body_type==ROUTER){
	  // A repeated 'router A router B' clause is a PARALLEL LANE, not a
	  // duplicate to overwrite. Direction is exactly what the clause
	  // names: no reverse edge is implied, so a one-way link stays
	  // one-way and a bidirectional link is declared both ways.
	  router_list[ROUTER][head_id][body_id].push_back(AnyNetEdge());
	  cur_lanes = &router_list[ROUTER][head_id][body_id];
	}
	state=LINK_WEIGHT;
	break ;
      default:
	cout<<"Anynet:Unknow parse state\n";
	assert(false);
	break;
      }

    } while(pos!=0);
    if(state!=LINK_WEIGHT &&
       state!=LINK_COST &&
       state!=BODY_TYPE){
      cout<<"Anynet:Incomplete parse of the line: "<<line<<endl;
    }

  }

  // A link with no explicit cost token routes by its latency (the historic
  // single-number semantics); `cost` was left unset at -1.
  for(size_t t = 0; t < router_list.size(); ++t){
    for(map<int, map<int, vector<AnyNetEdge> > >::iterator r =
	  router_list[t].begin(); r != router_list[t].end(); ++r){
      for(map<int, vector<AnyNetEdge> >::iterator d = r->second.begin();
	  d != r->second.end(); ++d){
	for(size_t lane = 0; lane < d->second.size(); ++lane){
	  if(d->second[lane].cost < 0){
	    d->second[lane].cost = d->second[lane].latency;
	  }
	}
      }
    }
  }

  //map verification, make sure the information contained in both maps
  //are the same
  assert(router_list[0].size() == router_list[1].size());

  //traffic generator assumes node list is sequential and starts at 0
  vector<int> node_check;
  for(map<int,int>::iterator i = node_list.begin();
      i!=node_list.end();
      i++){
    node_check.push_back(i->first);
  }
  sort(node_check.begin(), node_check.end());
  for(size_t i = 0; i<node_check.size(); i++){
    if((size_t)node_check[i] != i){
      cout<<"Anynet:booksim trafficmanager assumes sequential node numbering starting at 0\n";
      assert(false);
    }
  }
  
}
