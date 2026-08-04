cmake_minimum_required(VERSION 3.22...4.2)
project(metal_example_noc_multicast_bw)

add_executable(noc_multicast_bw)
target_sources(noc_multicast_bw PRIVATE noc_multicast_bw.cpp)

if(NOT TARGET TT::Metalium)
    find_package(TT-Metalium REQUIRED)
endif()
target_link_libraries(noc_multicast_bw PUBLIC TT::Metalium)
if(TARGET TT::CommonPCH)
    tt_reuse_precompile_headers(noc_multicast_bw TT::CommonPCH)
endif()
