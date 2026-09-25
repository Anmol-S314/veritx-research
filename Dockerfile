# Stage 1: Build all VeritX research tools
FROM ubuntu:22.04 AS builder

LABEL description="VeritX Research Tools — Booksim, Accelergy, Yosys, SymbiYosys, CBMC (gem5 + Timeloop added later)"

SHELL ["/bin/bash", "-c"]
ENV DEBIAN_FRONTEND=noninteractive
ENV MAKEFLAGS="-j$(nproc)"

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    bison \
    ccache \
    cmake \
    curl \
    flex \
    g++ \
    gcc \
    git \
    libboost-all-dev \
    libconfig++-dev \
    libffi-dev \
    libgoogle-perftools-dev \
    libgpm-dev \
    libncurses5-dev \
    libprotobuf-dev \
    libreadline-dev \
    libtinfo-dev \
    libyaml-cpp-dev \
    make \
    mercurial \
    ninja-build \
    pkg-config \
    protobuf-compiler \
    scons \
    python3 \
    python3-dev \
    python3-numpy \
    python3-matplotlib \
    python3-pip \
    python3-tk \
    swig \
    tcl-dev \
    wget \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt

# =============================================================================
# Booksim 2.0 — COPY from third_party/ (single source of truth)
# The host's third_party/booksim2/src/ carries our modifications:
#   - matrix traffic pattern (Timeloop bridge)
#   - VeritX: percentile stats, completion time, drain-on-unstable
#   - VeritX: trace-driven mode improvements
# Source kept at /opt/booksim2 so students can extend + recompile.
# =============================================================================
COPY third_party/booksim2/src/ /opt/booksim2/src/
RUN cd /opt/booksim2/src && make -j$(nproc) && \
    cp booksim /usr/local/bin/

# =============================================================================
# Accelergy (T3 — Topology energy estimation)
# Pinned by commit (C8): no moving HEAD/latest in the release image path.
# =============================================================================
ARG ACCELERGY_COMMIT=6911d15686ee7efdceba7d95605102df4472ae3a
RUN git init accelergy && cd accelergy && \
    git remote add origin https://github.com/Accelergy-Project/accelergy.git && \
    git fetch --depth 1 origin "$ACCELERGY_COMMIT" && \
    git checkout FETCH_HEAD && \
    pip3 install .

# =============================================================================
# Timeloop (T3 — data-movement model). Pinned to the last commit before the
# barvinok/isl/NTL dependency, so it builds from apt deps only (no heavy stack).
# C++ core only (timeloop-model/mapper); the pytimeloop bindings aren't needed —
# the mapping search is C++, our bridge is thin Python. `-Werror` is dropped
# because this 2022 code trips newer GCC's warnings.
# =============================================================================
RUN git clone --recurse-submodules https://github.com/Accelergy-Project/timeloop.git && \
    cd timeloop && git checkout 6b705056d7473a86d6439533879632d0979b85a1 && \
    git submodule update --init --recursive && \
    sed -i "s/'-Werror', //; s/-std=c++14/-std=c++17/" src/SConscript && \
    cd src && ln -s ../pat-public/src/pat . && cd .. && \
    scons -j$(nproc) && \
    cp build/timeloop-model build/timeloop-mapper build/timeloop-metrics /usr/local/bin/ && \
    find . -name "libtimeloop*.so" -exec cp {} /usr/local/lib/ \;

# =============================================================================
# Yosys (T4 — Formal Verification). Pinned by commit (C8).
# =============================================================================
ARG YOSYS_COMMIT=6f876ae0e2095753bac358c88f93bc27a62b3d9b
RUN pip3 install cmake && \
    git init yosys && cd yosys && \
    git remote add origin https://github.com/YosysHQ/yosys.git && \
    git fetch --depth 1 origin "$YOSYS_COMMIT" && \
    git checkout FETCH_HEAD && \
    git submodule update --init --recursive --depth 1 && \
    mkdir build && cd build && \
    cmake .. -DBUILD_EDA=ON -DENABLE_READLINE=OFF -DWITH_ABC=OFF \
        -DCMAKE_INSTALL_PREFIX=/usr/local && \
    make -j$(nproc) && \
    make install && \
    # CMake may miss some share files; copy them explicitly
    cp -r /opt/yosys/backends/smt2/smtio.py /usr/local/share/yosys/python3/ && \
    strip /usr/local/bin/yosys

# =============================================================================
# SymbiYosys (T4). Pinned by commit (C8).
# =============================================================================
ARG SBY_COMMIT=b1a1e98cba941ec8433f8dc27f416cd7bb7f14be
RUN git init sby && cd sby && \
    git remote add origin https://github.com/YosysHQ/sby.git && \
    git fetch --depth 1 origin "$SBY_COMMIT" && \
    git checkout FETCH_HEAD && \
    make install && \
    mkdir -p /usr/local/share/yosys/python3/ && \
    cp sbysrc/*.py /usr/local/share/yosys/python3/

# =============================================================================
# CBMC (T4). Pinned by commit (C8).
# =============================================================================
ARG CBMC_COMMIT=fd5dcee9e623c7d6539697abaafc15fbf73bd3ac
RUN git init cbmc && cd cbmc && \
    git remote add origin https://github.com/diffblue/cbmc.git && \
    git fetch --depth 1 origin "$CBMC_COMMIT" && \
    git checkout FETCH_HEAD && \
    cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DWITH_JBMC=OFF && \
    cmake --build build -j$(nproc) && \
    cmake --install build && \
    strip /usr/local/bin/cbmc

# =============================================================================
# ASTRA-sim + BookSim2 integration (serving-leg multi-die simulation)
# Builds the AstraSim_BookSim2 binary that uses our BookSim2 fork as the
# network backend. The event queue fix (advance_hook in Booksim2Fabric.hh)
# and the interactive main loop (main.cc) are included.
# =============================================================================
COPY third_party/astra-sim/ /opt/astra-sim-src/
COPY third_party/booksim2/ /opt/booksim2-canonical/
RUN mkdir -p /opt/astra-sim-build && cd /opt/astra-sim-build && \
    cmake /opt/astra-sim-src/build/astra_booksim2 \
      -DBOOKSIM2_SRC_DIR=/opt/booksim2-canonical && \
    cmake --build . -j$(nproc) && \
    cp bin/AstraSim_BookSim2 /usr/local/bin/

# Chakra protobuf Python stubs are pre-built in the source tree;
# copy them to a system-wide location for trace parsing.
RUN mkdir -p /usr/local/share/chakra && \
    cp /opt/astra-sim-src/extern/graph_frontend/chakra/build/lib/chakra/schema/protobuf/et_def_pb2.py \
       /usr/local/share/chakra/

# =============================================================================
# LLMServingSim (serving-leg traffic trace generation)
# =============================================================================
COPY third_party/llmservingsim/serving/ /opt/llmservingsim/serving/
COPY third_party/llmservingsim/configs/ /opt/llmservingsim/configs/
COPY third_party/llmservingsim/workloads/ /opt/llmservingsim/workloads/
COPY third_party/astra-sim/astra-sim/network_frontend/booksim2/examples/convert_chakra_trace.py \
     /opt/llmservingsim/convert_chakra_trace.py

# =============================================================================
# Python dependencies (shared across all tracks)
# =============================================================================
# z3 solver comes from the apt `z3` binary (runtime stage); smtbmc shells out to it
RUN pip3 install --no-cache-dir \
    pandas \
    seaborn \
    jupyter \
    click \
    pyyaml \
    'matplotlib>=3.10'

# =============================================================================
# Stage 2: Runtime image (slim)
# =============================================================================
FROM ubuntu:22.04

SHELL ["/bin/bash", "-c"]
ENV DEBIAN_FRONTEND=noninteractive

# Runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    bison \
    ca-certificates \
    flex \
    g++ \
    gcc \
    git \
    libboost-serialization1.74.0 \
    libconfig++9v5 \
    libgoogle-perftools4 \
    libncurses6 \
    libprotobuf-dev \
    libyaml-cpp0.7 \
    make \
    python3 \
    python3-numpy \
    python3-matplotlib \
    python3-pip \
    python3-tk \
    verilator \
    wget \
    z3 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local/bin/ /usr/local/bin/
COPY --from=builder /usr/local/lib/ /usr/local/lib/
COPY --from=builder /usr/local/share/ /usr/local/share/
COPY --from=builder /usr/lib/python3/dist-packages/ /usr/lib/python3/dist-packages/
# Booksim source (with matrix pattern) so students can extend + recompile
COPY --from=builder /opt/booksim2 /opt/booksim2
# ASTRA-sim + BookSim2 integration binary
COPY --from=builder /usr/local/bin/AstraSim_BookSim2 /usr/local/bin/AstraSim_BookSim2
# Chakra protobuf Python stubs (for trace parsing)
COPY --from=builder /usr/local/share/chakra/ /usr/local/share/chakra/
# LLMServingSim trace generation pipeline
COPY --from=builder /opt/llmservingsim/ /opt/llmservingsim/
# psc-ns3 — COPY from third_party/
COPY third_party/psc-ns3/ /opt/psc-ns3/
# Timeloop's bundled problem shapes (baked search path is /opt/timeloop) so
# students can reference predefined shapes; T3's own problem.yaml is self-contained
COPY --from=builder /opt/timeloop/problem-shapes /opt/timeloop/problem-shapes

# Environment: ASTRA-sim + Chakra + LLMServingSim on PYTHONPATH
ENV PYTHONPATH="/usr/local/share/chakra:/opt/llmservingsim:${PYTHONPATH}"

RUN ldconfig

ENV PYTHONPATH="/usr/local/share/yosys/python3:${PYTHONPATH}"

# Fix matplotlib/numpy compatibility (apt version compiled against numpy 1.x)
# Remove apt scipy (ABI-incompatible with numpy 2.x); none of our tracks use it
RUN pip3 install --upgrade --no-cache-dir 'matplotlib>=3.10' && \
    pip3 uninstall -y scipy 2>/dev/null; \
    rm -rf /usr/lib/python3/dist-packages/scipy* /usr/lib/python3/dist-packages/scipy/ 2>/dev/null; true

WORKDIR /workspace
CMD ["bash"]
