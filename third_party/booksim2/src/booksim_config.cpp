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

/*booksim_config.cpp
 *
 *Contains all the configurable parameters in a network
 *
 */


#include "booksim.hpp"
#include "booksim_config.hpp"

BookSimConfig::BookSimConfig( )
{ 
  //========================================================
  // Network options
  //========================================================

  // Channel length listing file
  AddStrField( "channel_file", "" ) ;

  // Versioned per-channel measurement dump (veritx/channel-activity/v1).
  // Empty (default) disables emission entirely: existing runs are
  // byte-identical with or without this key present but empty.
  AddStrField( "channel_activity_output", "" ) ;

  // Sampled per-window series (veritx/channel-timeseries/v1). Fully
  // gated: an empty output path or a non-positive period disables
  // sampling entirely (GetSimTime keeps one idle branch; no snapshots,
  // no file). Attribution keys are required when enabled: an
  // unlabeled measurement is refused rather than emitted anonymous.
  AddStrField( "channel_timeseries_output", "" ) ;
  _int_map["sample_period_cycles"] = 0 ;
  AddStrField( "run_hash", "" ) ;
  _int_map["link_capacity_flits_per_cycle"] = 1 ;
  AddStrField( "run_provenance_backend", "booksim" ) ;
  AddStrField( "run_provenance_version", "veritx-fork" ) ;
  AddStrField( "run_binary_hash", "" ) ;
  AddStrField( "run_input_hashes", "" ) ;

  // Physical sub-networks
  _int_map["subnets"] = 1;
  _int_map["class_subnet"] = -1;       // per class: fixed subnet, -1 = stock choice
  AddStrField("class_subnet", "");     // workaround to allow for vector specification

  //==== Topology options =======================
  AddStrField( "topology", "torus" );
  _int_map["k"] = 8; //network radix
  _int_map["n"] = 2; //network dimension
  _int_map["c"] = 1; //concentration
  _int_map["o"] = 0; //GEC: output channels/dim/node (0 = default to k-1)
  _int_map["d"] = 0; //GEC: channel radix / sinks per channel (0 = default to 1)
  _int_map["mesh"] = 0; //GEC: 1 = nearest-neighbor mesh graph, 0 = full express graph
  _int_map["hybrid"] = 0; //GEC: 1 = nearest-neighbor mesh graph + o MECS express channels/dim layered on top, per-hop congestion-and-hopcount routed choice between them (mutually exclusive with mesh=1)

  //---- Srota NoC (topology = srota) -----------------------------------
  // Names track the spec's register names so a config file reads like the
  // programming model; see networks/srota.hpp for the full mapping.
  //   TOPO-003  = SSM-UARCH-TOPO-003  rev 0.3  Topology / MECS
  //   ROUTE-001 = SSM-UARCH-ROUTE-001 rev 0.3  Routing Algorithm
  //   TEL-004   = SSM-UARCH-TEL-004   rev 0.3  Telemetry
  _int_map["srota_mecs"] = 3;             //TOPO_MECS_ENABLE: bit0 row express, bit1 column express. 0 = plain concentrated mesh (the ablation baseline, TOPO-003 5)
  _int_map["srota_drop_latency"] = 1;     //TOPO_DROP_LATENCY: 1 = single-cycle drop, 2 = repeatered fallback at high radix (TOPO-003 6.2)
  _int_map["srota_island_col_map"] = 0;   //TOPO_ISLAND_COL_MAP: bitmap of QoS island columns. Requires MECS on both dims (TOPO-003 4.4); checked against invariant I-ISL by TP-V2 at elaboration
  _int_map["srota_path_en"] = 7;          //ROUTE_PATH_EN: bit0 row-first, bit1 column-first, bit2 Valiant. Bit0 is mandatory (ROUTE-001 14.3). 7 is the shipping default and the RT-R7 configuration
  _int_map["srota_cong_thresh"] = 8;      //ROUTE_CONGESTION_THRESH: Plane-T occupancy nibble above which a candidate counts as congested (ROUTE-001 14.1)
  _int_map["srota_epoch_len"] = 1024;     //ROUTE_EPOCH_LEN: flow-epoch length in cycles for the path cache (ROUTE-001 10.3)
  _int_map["srota_force_shape"] = -1;     //ROUTE_DEBUG_FORCE_SHAPE: -1 = off, else force every flow to shape 0..3 (ROUTE-001 14.1)
  _int_map["srota_flow_cache_size"] = 64; //Flow-epoch cache entries per FIU (ROUTE-001 10.4). Smaller = more hash collisions = more flows adopting another flow's path
  _int_map["srota_tel_period"] = 4;       //Plane-T sample period in Plane-D cycles; 4 models 1 GHz telemetry against a 4 GHz data plane (TEL-004 2.1)
  _int_map["srota_tel_latency"] = 8;      //Plane-T publication delay in Plane-D cycles: fixed ring-tree depth, independent of Plane-D congestion (TEL-004 3)
  _int_map["srota_cdg_radix"] = 4;        //F1: radix of the abstraction the static channel-dependency-graph check runs on, exhaustively (ROUTE-001 4.4 specifies 4x4). 0 disables the check
  AddStrField( "srota_vc_policy", "rank" );//Deadlock-avoidance mechanism: none | shape | rank | oneshape. See srota.hpp design note 3 -- this is the RT-R7 experiment axis
  // Planes (TOPO-003 5, 13.2 TOPO_PLANE_PRESENT). bit0 D (mandatory), bit1 C, bit2 T.
  // D = MECS data plane; C = conventional mesh control plane on subnet 1 (needs subnets=2);
  // T = the telemetry model the Plane-D overlay reads. 5 = D+T, the pre-planes behaviour.
  _int_map["srota_planes"] = 5;
  _int_map["srota_d_num_vcs"] = 0;        //Plane-D VC count; 0 = num_vcs. num_vcs must be >= every plane's count
  AddStrField( "srota_router", "iq" );    //Plane-D router: iq (per-input VC buffers) | sidebuf (VC-002 staging latch + shared side buffer)
  _int_map["srota_sb_depth"] = 8;         //Side-buffer capacity in flits, shared per router (VC-002 13.6: 4-16, default 8). vc_buf_size is the staging window
  _int_map["srota_sb_watermark"] = 6;     //VC_SIDEBUF_WATERMARK: occupancy above which the router raises a Plane-T congestion hint
  _float_map["srota_isl_rate"] = 0.0;     //Island rate regulator, per QoS class, flits/cycle; <=0 = unregulated (accounting only)
  AddStrField( "srota_isl_rate", "" );    // workaround to allow for vector specification
  _int_map["srota_isl_burst"] = 8;        //Island token-bucket depth, flits
  AddStrField( "srota_isl_class", "class" ); //QoS class_id source: class (traffic class) | slack (PKT-008 slack field)
  AddStrField( "srota_isl_route", "any" );   //any | colfirst. colfirst routes island-bound flows column-first -- the rule that makes I-ISL hold (SROTA.md finding 2)
  _int_map["srota_deflect"] = 0;          //Deflection (misrouting) on Plane D: 0 = off, 1 = on. A packet blocked on its productive port may take a non-productive one instead of waiting for credit. Needs an escape VC -- see srota_deflect_esc_vcs
  _int_map["srota_deflect_max"] = 4;      //Deflection budget per packet. At the budget a packet is minimal-only, which is what bounds its hop count and makes deflection livelock-free
  _int_map["srota_deflect_esc_vcs"] = 1;  //VCs [0, n) are the escape network: deterministic route only, never deflected. Duato's escape channel -- deadlock freedom rests on this subgraph being acyclic, which is what the F1 CDG check verifies
  _int_map["srota_planec_vcs"] = 3;       //Plane-C VCs: REQ / RSP / SNP (VC-002 3.2)
  _int_map["srota_planec_vc_buf"] = 4;    //Plane-C per-VC depth (VC-002 3.2 VC_PLANEC_DEPTH_*)

  AddStrField( "routing_function", "none" );

  //simulator tries to correclty adjust latency for node/router placement
  _int_map["use_noc_latency"] = 1;


  //used for noc latency calcualtion for network with concentration
  _int_map["x"] = 8; //number of routers in X
  _int_map["y"] = 8; //number of routers in Y
  _int_map["xr"] = 1; //number of nodes per router in X only if c>1
  _int_map["yr"] = 1; //number of nodes per router in Y only if c>1


  _int_map["link_failures"] = 0; //legacy
  _int_map["fail_seed"]     = 0; //legacy
  AddStrField( "fail_seed", "" ); // workaround to allow special "time" value

  //==== Single-node options ===============================

  _int_map["in_ports"]  = 5;
  _int_map["out_ports"] = 5;

  //========================================================
  // Router options
  //========================================================

  //==== General options ===================================

  AddStrField( "router", "iq" ); 

  _int_map["output_delay"] = 0;
  _int_map["credit_delay"] = 0;
  _float_map["internal_speedup"] = 1.0;

  //with switch speedup flits requires otuput buffering
  //full output buffer will cancel switch allocation requests
  //default setting is unlimited
  _int_map["output_buffer_size"] = -1;

  // enable next-hop-output queueing
  _int_map["noq"] = 0;

  //==== Input-queued ======================================

  // Control of virtual channel speculation
  _int_map["speculative"] = 0 ;
  _int_map["spec_check_elig"] = 1 ;
  _int_map["spec_check_cred"] = 1 ;
  _int_map["spec_mask_by_reqs"] = 0 ;
  AddStrField("spec_sw_allocator", "prio");
  
  _int_map["num_vcs"]         = 16;  
  _int_map["vc_buf_size"]     = 8;  //per vc buffer size
  _int_map["buf_size"]        = -1; //shared buffer size
  AddStrField("buffer_policy", "private"); //buffer sharing policy

  _int_map["private_bufs"] = -1;
  _int_map["private_buf_size"] = 1;
  AddStrField("private_buf_size", "");
  _int_map["private_buf_start_vc"] = -1;
  AddStrField("private_buf_start_vc", "");
  _int_map["private_buf_end_vc"] = -1;
  AddStrField("private_buf_end_vc", "");

  _int_map["max_held_slots"] = -1;

  _int_map["feedback_aging_scale"] = 1;
  _int_map["feedback_offset"] = 0;

  _int_map["wait_for_tail_credit"] = 0; // reallocate a VC before a tail credit?
  _int_map["vc_busy_when_full"] = 0; // mark VCs as in use when they have no credit available
  _int_map["vc_prioritize_empty"] = 0; // prioritize empty VCs over non-empty ones in VC allocation
  _int_map["vc_priority_donation"] = 0; // allow high-priority flits to donate their priority to low-priority that they are queued up behind
  _int_map["vc_shuffle_requests"] = 0; // rearrange VC allocator requests to avoid unfairness

  _int_map["hold_switch_for_packet"] = 0; // hold a switch config for the entire packet

  _int_map["input_speedup"]     = 1;  // expansion of input ports into crossbar
  _int_map["output_speedup"]    = 1;  // expansion of output ports into crossbar

  _int_map["routing_delay"]    = 1;  
  _int_map["vc_alloc_delay"]   = 1;  
  _int_map["sw_alloc_delay"]   = 1;  
  _int_map["st_prepare_delay"] = 0;
  _int_map["st_final_delay"]   = 1;

  //==== Event-driven =====================================

  _int_map["vct"] = 0; 

  //==== Allocators ========================================

  AddStrField( "vc_allocator", "islip" ); 
  AddStrField( "sw_allocator", "islip" ); 

  // Srota three-level arbiter (SSM-UARCH-ROUTE-001 rev 0.3 section 11.2),
  // selected with sw_allocator = srota_arb. Each level can be disabled
  // independently, which is how an M3 run says which level did the work
  // rather than only that the arbiter helped.
  _int_map["srota_arb_l0_golden"]     = 1;   // golden rotation, F3
  _int_map["srota_arb_l1_slack"]      = 1;   // slack class
  _int_map["srota_arb_l2_stc"]        = 1;   // STC batch epoch, F4
  _int_map["srota_arb_golden_epoch"]  = 64;  // cycles per golden window
  _int_map["srota_arb_golden_windows"]= 16;  // windows in the rotation
  
  AddStrField( "arb_type", "round_robin" );
  
  _int_map["alloc_iters"] = 1;
  
  //==== Traffic ========================================

  _int_map["classes"] = 1;

  AddStrField( "traffic", "uniform" );
  AddStrField( "trace_file", "" );
  AddStrField( "trace_packet_log", "" );

  _int_map["class_priority"] = 0;
  AddStrField("class_priority", ""); // workaraound to allow for vector specification

  _int_map["perm_seed"] = 0; // seed value for random permuation trafficpattern generator
  AddStrField("perm_seed", ""); // workaround to allow special "time" value

  _float_map["injection_rate"]       = 0.1;
  AddStrField("injection_rate", ""); // workaraound to allow for vector specification
  
  _int_map["injection_rate_uses_flits"] = 0;

  // number of flits per packet
  _int_map["packet_size"] = 1;
  AddStrField("packet_size", ""); // workaraound to allow for vector specification

  // if multiple values are specified per class, set probabilities for each
  _int_map["packet_size_rate"] = 1;
  AddStrField("packet_size_rate", ""); // workaraound to allow for vector specification

  AddStrField( "injection_process", "bernoulli" );

  _float_map["burst_alpha"] = 0.5; // burst interval
  _float_map["burst_beta"]  = 0.5; // burst length
  _float_map["burst_r1"] = -1.0; // burst rate

  AddStrField( "priority", "none" );  // message priorities

  _int_map["batch_size"] = 1000;
  _int_map["batch_count"] = 1;
  _int_map["max_outstanding_requests"] = 0; // 0 = unlimited

  // Use read/write request reply scheme
  _int_map["use_read_write"] = 0;
  AddStrField("use_read_write", ""); // workaraound to allow for vector specification
  _float_map["write_fraction"] = 0.5;
  AddStrField("write_fraction", "");

  // Control assignment of packets to VCs
  _int_map["read_request_begin_vc"] = 0;
  _int_map["read_request_end_vc"] = 5;
  _int_map["write_request_begin_vc"] = 2;
  _int_map["write_request_end_vc"] = 7;
  _int_map["read_reply_begin_vc"] = 8;
  _int_map["read_reply_end_vc"] = 13;
  _int_map["write_reply_begin_vc"] = 10;
  _int_map["write_reply_end_vc"] = 15;

  // Control Injection of Packets into Replicated Networks
  _int_map["read_request_subnet"] = 0;
  _int_map["read_reply_subnet"] = 0;
  _int_map["write_request_subnet"] = 0;
  _int_map["write_reply_subnet"] = 0;

  // Set packet length in flits
  _int_map["read_request_size"]  = 1;
  AddStrField("read_request_size", ""); // workaraound to allow for vector specification
  _int_map["write_request_size"] = 1;
  AddStrField("write_request_size", ""); // workaraound to allow for vector specification
  _int_map["read_reply_size"]    = 1;
  AddStrField("read_reply_size", ""); // workaraound to allow for vector specification
  _int_map["write_reply_size"]   = 1;
  AddStrField("write_reply_size", ""); // workaraound to allow for vector specification

  //==== Simulation parameters ==========================

  // types:
  //   latency    - average + latency distribution for a particular injection rate
  //   throughput - sustained throughput for a particular injection rate

  AddStrField( "sim_type", "latency" );

  _int_map["warmup_periods"] = 3; // number of samples periods to "warm-up" the simulation

  _int_map["sample_period"] = 1000; // how long between measurements
  _int_map["max_samples"]   = 10;   // maximum number of sample periods in a simulation

  // whether or not to measure statistics for a given traffic class
  _int_map["measure_stats"] = 1;
  AddStrField("measure_stats", ""); // workaround to allow for vector specification
  //whether to enable per pair statistics, caution N^2 memory usage
  _int_map["pair_stats"] = 0;

  // if avg. latency exceeds the threshold, assume unstable
  _float_map["latency_thres"] = 500.0;
  AddStrField("latency_thres", ""); // workaround to allow for vector specification

   // consider warmed up once relative change in latency / throughput between successive iterations is smaller than this
  _float_map["warmup_thres"] = 0.05;
  AddStrField("warmup_thres", ""); // workaround to allow for vector specification
  _float_map["acc_warmup_thres"] = 0.05;
  AddStrField("acc_warmup_thres", ""); // workaround to allow for vector specification

  // consider converged once relative change in latency / throughput between successive iterations is smaller than this
  _float_map["stopping_thres"] = 0.05;
  AddStrField("stopping_thres", ""); // workaround to allow for vector specification
  _float_map["acc_stopping_thres"] = 0.05;
  AddStrField("acc_stopping_thres", ""); // workaround to allow for vector specification

  _int_map["sim_count"]     = 1;   // number of simulations to perform


  _int_map["include_queuing"] =1; // non-zero includes source queuing latency

  //  _int_map["reorder"]         = 0;  // know what you're doing

  //_int_map["flit_timing"]     = 0;  // know what you're doing
  //_int_map["split_packets"]   = 0;  // know what you're doing

  _int_map["seed"]            = 0; //random seed for simulation, e.g. traffic 
  AddStrField("seed", ""); // workaround to allow special "time" value

  _int_map["print_activity"] = 0;

  _int_map["print_csv_results"] = 0;

  _int_map["deadlock_warn_timeout"] = 256;

  _int_map["viewer_trace"] = 0;

  AddStrField("watch_file", "");
  
  AddStrField("watch_flits", "");
  AddStrField("watch_packets", "");
  AddStrField("watch_transactions", "");

  AddStrField("watch_out", "");

  AddStrField("stats_out", "");

#ifdef TRACK_FLOWS
  AddStrField("injected_flits_out", "");
  AddStrField("received_flits_out", "");
  AddStrField("stored_flits_out", "");
  AddStrField("sent_flits_out", "");
  AddStrField("outstanding_credits_out", "");
  AddStrField("ejected_flits_out", "");
  AddStrField("active_packets_out", "");
#endif

#ifdef TRACK_CREDITS
  AddStrField("used_credits_out", "");
  AddStrField("free_credits_out", "");
  AddStrField("max_credits_out", "");
#endif

  // batch only -- packet sequence numbers
  AddStrField("sent_packets_out", "");
  
  //==================Power model params=====================
  _int_map["sim_power"] = 0;
  AddStrField("power_output_file","pwr_tmp");
  AddStrField("tech_file", "");
  _int_map["channel_width"] = 128;
  _int_map["channel_sweep"] = 0;

  //==================Network file===========================
  AddStrField("network_file","");
  // VeritX (B3.7b): optional path for the anynet executed-route dump.
  // Empty (default) means no dump and no behavior change.
  AddStrField("routing_dump_file","");
  AddStrField("hybrid_gec_observation_file","");
}



PowerConfig::PowerConfig( )
{ 

  _int_map["H_INVD2"] = 0;
  _int_map["W_INVD2"] = 0;
  _int_map["H_DFQD1"] = 0;
  _int_map["W_DFQD1"] = 0;
  _int_map["H_ND2D1"] = 0;
  _int_map["W_ND2D1"] = 0;
  _int_map["H_SRAM"] = 0;
  _int_map["W_SRAM"] = 0;
  _float_map["Vdd"] = 0;
  _float_map["R"] = 0;
  _float_map["IoffSRAM"] = 0;
  _float_map["IoffP"] = 0;
  _float_map["IoffN"] = 0;
  _float_map["Cg_pwr"] = 0;
  _float_map["Cd_pwr"] = 0;
  _float_map["Cgdl"] = 0;
  _float_map["Cg"] = 0;
  _float_map["Cd"] = 0;
  _float_map["LAMBDA"] = 0;
  _float_map["MetalPitch"] = 0;
  _float_map["Rw"] = 0;
  _float_map["Cw_gnd"] = 0;
  _float_map["Cw_cpl"] = 0;
  _float_map["wire_length"] = 0;

}