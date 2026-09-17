# Fixed CMakeLists.txt for AstraSim_BookSim2 frontend
# Finds pre-built AstraSim + BookSim2Fabric libs from parent builds

# NOTE: all paths here are REPO-RELATIVE (computed from this file's location:
# <repo>/third_party/astra-sim/astra-sim/network_frontend/booksim2/).
# The previous version hardcoded /home/datavex/veritx-research/... paths from
# the old serving/astra-sim layout — unbuildable on any other machine or
# checkout path.

cmake_minimum_required(VERSION 3.15)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release)
endif()
project(AstraSim_BookSim2)

# Repo roots derived from this file (four levels up = third_party/astra-sim,
# six levels up = repo root)
get_filename_component(ASTRA_ROOT "${CMAKE_CURRENT_LIST_DIR}/../../.." ABSOLUTE)
get_filename_component(REPO_ROOT "${CMAKE_CURRENT_LIST_DIR}/../../../../.." ABSOLUTE)

# Paths to pre-built libraries
set(ASTRASIM_LIB_DIR "${ASTRA_ROOT}/build/lib")
set(ASTRASIM_SRC_DIR "${ASTRA_ROOT}")
set(BOOKSIM2FABRIC_LIB_DIR "${ASTRA_ROOT}/extern/network_backend/booksim2/build")
set(BOOKSIM2FABRIC_SRC_DIR "${ASTRA_ROOT}/extern/network_backend/booksim2")
set(BOOKSIM2_SRC_DIR "${REPO_ROOT}/third_party/booksim2/src")

# Find pre-built libraries
find_library(ASTRASIM_LIB AstraSim PATHS ${ASTRASIM_LIB_DIR} NO_DEFAULT_PATH)
find_library(BOOKSIM2FABRIC_LIB BookSim2Fabric PATHS ${BOOKSIM2FABRIC_LIB_DIR} NO_DEFAULT_PATH)

if(NOT ASTRASIM_LIB)
    message(FATAL_ERROR "libAstraSim.a not found in ${ASTRASIM_LIB_DIR}")
endif()
if(NOT BOOKSIM2FABRIC_LIB)
    message(FATAL_ERROR "libBookSim2Fabric.a not found in ${BOOKSIM2FABRIC_LIB_DIR}")
endif()

message(STATUS "Found AstraSim: ${ASTRASIM_LIB}")
message(STATUS "Found BookSim2Fabric: ${BOOKSIM2FABRIC_LIB}")

# Source files
file(GLOB srcs_common ${CMAKE_CURRENT_SOURCE_DIR}/common/*.cc)

add_executable(AstraSim_BookSim2
    ${srcs_common}
    ${CMAKE_CURRENT_SOURCE_DIR}/main.cc
    ${CMAKE_CURRENT_SOURCE_DIR}/Booksim2NetworkApi.cc)

target_link_libraries(AstraSim_BookSim2 PRIVATE ${ASTRASIM_LIB})
target_link_libraries(AstraSim_BookSim2 PRIVATE ${BOOKSIM2FABRIC_LIB})

# Also need protobuf for AstraSim
find_package(Protobuf REQUIRED)
target_link_libraries(AstraSim_BookSim2 PRIVATE ${Protobuf_LIBRARIES})

# Include directories
target_include_directories(AstraSim_BookSim2 PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/include/
    ${ASTRASIM_SRC_DIR}
    ${ASTRASIM_SRC_DIR}/extern/
    ${ASTRASIM_SRC_DIR}/extern/helper
    ${ASTRASIM_SRC_DIR}/extern/graph_frontend/chakra/
    ${ASTRASIM_SRC_DIR}/extern/graph_frontend/chakra/schema/protobuf
    ${ASTRASIM_SRC_DIR}/extern/graph_frontend/chakra/src/third_party/utils
    ${BOOKSIM2FABRIC_SRC_DIR}
    ${BOOKSIM2_SRC_DIR}
    ${BOOKSIM2_SRC_DIR}/arbiters
    ${BOOKSIM2_SRC_DIR}/allocators
    ${BOOKSIM2_SRC_DIR}/routers
    ${BOOKSIM2_SRC_DIR}/networks
    ${BOOKSIM2_SRC_DIR}/power
    ${Protobuf_INCLUDE_DIR}
)

set_target_properties(AstraSim_BookSim2 PROPERTIES COMPILE_WARNING_AS_ERROR OFF)
set_target_properties(AstraSim_BookSim2
    PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}/../bin/
    LIBRARY_OUTPUT_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}/../lib/
    ARCHIVE_OUTPUT_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}/../lib/
)
