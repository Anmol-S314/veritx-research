# VeritX — BookSim2 network backend for ASTRA-sim.
# Compiles our booksim2 fork (embedding API, veritx_ext hooks, multicast)
# into a static library the frontend links against.

cmake_minimum_required(VERSION 3.15)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if (NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release)
endif ()

project(BookSim2Fabric)

# Location of the vendored booksim2 fork. Default: the ASTRA-sim tree's own
# copy; pass -DBOOKSIM2_SRC_DIR=<path> to point at another checkout.
set(BOOKSIM2_SRC_DIR "${CMAKE_CURRENT_SOURCE_DIR}/booksim2"
    CACHE PATH "Path to the booksim2 fork source tree (src/)")

set(BOOKSIM2_ROOT "${BOOKSIM2_SRC_DIR}/src")

file(GLOB BOOKSIM2_CPP ${BOOKSIM2_ROOT}/*.cpp ${BOOKSIM2_ROOT}/*/*.cpp)
list(APPEND BOOKSIM2_CPP ${BOOKSIM2_ROOT}/lex.yy.c ${BOOKSIM2_ROOT}/y.tab.c)

add_library(BookSim2Fabric STATIC ${BOOKSIM2_CPP}
            ${CMAKE_CURRENT_SOURCE_DIR}/Booksim2Fabric.cc)

target_include_directories(BookSim2Fabric PUBLIC
        ${CMAKE_CURRENT_SOURCE_DIR}
        ${CMAKE_CURRENT_SOURCE_DIR}/../../..
        ${BOOKSIM2_ROOT}
        ${BOOKSIM2_ROOT}/arbiters
        ${BOOKSIM2_ROOT}/allocators
        ${BOOKSIM2_ROOT}/routers
        ${BOOKSIM2_ROOT}/networks
        ${BOOKSIM2_ROOT}/power
)

set_target_properties(BookSim2Fabric PROPERTIES COMPILE_WARNING_AS_ERROR OFF)
