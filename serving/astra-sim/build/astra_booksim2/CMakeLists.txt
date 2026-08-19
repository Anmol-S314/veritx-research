cmake_minimum_required(VERSION 3.15)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if (NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release)
endif ()
set(CMAKE_CXX_FLAGS_RELEASE "-O3")
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -Wno-error")

project(AstraSim_BookSim2)

# Compile AstraSim library
add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../../ AstraSim)

# our booksim2 fork + fabric wrapper as the network backend
add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../../extern/network_backend/booksim2/ BookSim2Fabric)
add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../../astra-sim/network_frontend/booksim2/ AstraSim_BookSim2)
