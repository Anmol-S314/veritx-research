cmake_minimum_required(VERSION 3.15)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if (NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release)
endif ()

project(AstraSim_BookSim2)

# VeritX: the embedded fabric frontend must compile its BookSim headers from ONE
# fork -- the canonical ``third_party/booksim2`` that standalone BookSim
# qualification also uses. The nested ``extern/network_backend/booksim2/booksim2``
# copy is vendored third-party and is NOT an implementation authority; it is kept
# on the include path only as a fallback for a standalone configure that does not
# pass -DBOOKSIM2_SRC_DIR (the qualification build always passes it).
if (NOT DEFINED BOOKSIM2_SRC_DIR)
    set(BOOKSIM2_SRC_DIR
            "${CMAKE_CURRENT_SOURCE_DIR}/../../../extern/network_backend/booksim2/booksim2"
            CACHE PATH "Canonical booksim2 fork source tree")
endif ()

file(GLOB srcs_common
        ${CMAKE_CURRENT_SOURCE_DIR}/common/*.cc
)

add_executable(AstraSim_BookSim2 ${srcs_common} ${CMAKE_CURRENT_SOURCE_DIR}/main.cc ${CMAKE_CURRENT_SOURCE_DIR}/Booksim2NetworkApi.cc)

target_link_libraries(AstraSim_BookSim2 LINK_PRIVATE AstraSim)
target_link_libraries(AstraSim_BookSim2 LINK_PRIVATE BookSim2Fabric)

target_link_directories(AstraSim_BookSim2 PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/../../../build/astra_booksim2/build/lib
        ${CMAKE_CURRENT_SOURCE_DIR}/../../../build/astra_booksim2/build/BookSim2Fabric
)

target_include_directories(AstraSim_BookSim2 PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/include/
        ${CMAKE_CURRENT_SOURCE_DIR}/../../../
        ${CMAKE_CURRENT_SOURCE_DIR}/../../../extern/
        ${CMAKE_CURRENT_SOURCE_DIR}/../../../extern/helper
        ${CMAKE_CURRENT_SOURCE_DIR}/../../../extern/helper/spdlog/include
        ${CMAKE_CURRENT_SOURCE_DIR}/../../../extern/helper/fmt/include
        ${CMAKE_CURRENT_SOURCE_DIR}/../../../extern/network_backend/booksim2
        ${CMAKE_CURRENT_SOURCE_DIR}/../../../extern/graph_frontend/chakra
        ${CMAKE_CURRENT_SOURCE_DIR}/../../../extern/graph_frontend/chakra/schema/protobuf
        ${CMAKE_CURRENT_SOURCE_DIR}/../../../extern/graph_frontend/chakra/src/third_party/utils
        # VeritX: canonical fork FIRST -- this is the honest source of the
        # embedded fabric's headers (must match the linked BookSim2Fabric).
        ${BOOKSIM2_SRC_DIR}/src
        ${BOOKSIM2_SRC_DIR}/src/arbiters
        ${BOOKSIM2_SRC_DIR}/src/allocators
        ${BOOKSIM2_SRC_DIR}/src/routers
        ${BOOKSIM2_SRC_DIR}/src/networks
        ${BOOKSIM2_SRC_DIR}/src/power
        # fallback only; not an authority (see BOOKSIM2_SRC_DIR note above)
        ${CMAKE_CURRENT_SOURCE_DIR}/../../../extern/network_backend/booksim2/booksim2/src
        ${CMAKE_CURRENT_SOURCE_DIR}/../../../extern/network_backend/booksim2/booksim2/src/arbiters
        ${CMAKE_CURRENT_SOURCE_DIR}/../../../extern/network_backend/booksim2/booksim2/src/allocators
        ${CMAKE_CURRENT_SOURCE_DIR}/../../../extern/network_backend/booksim2/booksim2/src/routers
        ${CMAKE_CURRENT_SOURCE_DIR}/../../../extern/network_backend/booksim2/booksim2/src/networks
        ${CMAKE_CURRENT_SOURCE_DIR}/../../../extern/network_backend/booksim2/booksim2/src/power
)

set_target_properties(AstraSim_BookSim2 PROPERTIES COMPILE_WARNING_AS_ERROR OFF)
set_target_properties(AstraSim_BookSim2 PROPERTIES
        # VeritX: output to the source-tree bin/ so the Python simulator
        # (which reads network_frontend/booksim2/bin/) always gets the
        # freshly-built binary regardless of where the build dir is.
        RUNTIME_OUTPUT_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}/bin/
        LIBRARY_OUTPUT_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}/lib/
        ARCHIVE_OUTPUT_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}/lib/
)
