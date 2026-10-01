# Base image is digest-pinned (C8/R4.1). Override with
#   --build-arg UBUNTU_IMAGE=ubuntu:22.04@sha256:<new-digest>
# to move it deliberately; a mutable tag is not used in the release path.
ARG UBUNTU_IMAGE=ubuntu:22.04@sha256:b8b6ee6aa931ecd9d0d952abc34dc0e5f7c6a30c6bb71b079fe399fde0329c02

# Stage 1: Build all VeritX research tools
FROM ${UBUNTU_IMAGE} AS builder

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

# Git resilience for every network fetch below (accelergy, timeloop, yosys,
# sby, cbmc). The image build clones from GitHub at build time; disabling the
# low-speed abort and enlarging the post buffer keeps a slow-but-progressing
# transfer from being killed as if it had stalled.
RUN git config --global http.lowSpeedLimit 0 && \
    git config --global http.lowSpeedTime 999999 && \
    git config --global http.postBuffer 524288000 && \
    git config --global advice.detachedHead false

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
# This step fetches from GitHub at build time; two things made it flaky.
#  1. `--depth 1` submodule clones intermittently fail with "Fetched in
#     submodule path 'X', but it did not contain <sha>" — the shallow clone
#     does not carry the pinned commit. Fetch full submodule history instead.
#  2. Transient network stalls; retry and disable git's low-speed abort.
RUN pip3 install cmake && \
    git config --global http.lowSpeedLimit 0 && \
    git config --global http.lowSpeedTime 999999 && \
    git config --global http.postBuffer 524288000 && \
    git init yosys && cd yosys && \
    git remote add origin https://github.com/YosysHQ/yosys.git && \
    for i in 1 2 3 4 5; do git fetch --depth 1 origin "$YOSYS_COMMIT" && break || sleep 10; done && \
    git checkout FETCH_HEAD && \
    for i in 1 2 3 4 5; do git submodule update --init --recursive && break || sleep 10; done && \
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
# Generate the flex/bison parser sources the BookSim2Fabric CMake globs for
# (.dockerignore keeps the host-generated ones out of the build context, so
# without this the glob is empty and CMake fails with "No SOURCES given to
# target: BookSim2Fabric").
RUN cd /opt/booksim2-canonical/src && flex config.l && bison -y -d config.y
# Regenerate the Chakra protobuf bindings with the container's protoc (the
# host copies were generated by a newer protoc and clash with 22.04's).
RUN cd /opt/astra-sim-src/extern/graph_frontend/chakra/schema/protobuf && \
    protoc --cpp_out=. --python_out=. --proto_path=. et_def.proto
RUN mkdir -p /opt/astra-sim-build && cd /opt/astra-sim-build && \
    cmake /opt/astra-sim-src/build/astra_booksim2 \
      -DBOOKSIM2_SRC_DIR=/opt/booksim2-canonical && \
    cmake --build . -j$(nproc) && \
    cp /opt/astra-sim-src/astra-sim/network_frontend/booksim2/bin/AstraSim_BookSim2 /usr/local/bin/
# Host-ABI bridge. The repo's AstraSim_BookSim2 is a dual-mode wrapper: on a
# host it execs the sibling .real; in this image it execs
#   /opt/hostabi/ld-linux-x86-64.so.2 --library-path /opt/hostabi /opt/hostabi/AstraSim_BookSim2
# when present. Nothing used to create /opt/hostabi, so the wrapper always
# fell through to a host-built .real (glibc 2.38 / libprotobuf.so.32 - cannot
# load under Ubuntu 22.04). Populate it with the container-native binary.
RUN mkdir -p /opt/hostabi && \
    cp /opt/astra-sim-src/astra-sim/network_frontend/booksim2/bin/AstraSim_BookSim2.real /opt/hostabi/AstraSim_BookSim2 && \
    cp /lib64/ld-linux-x86-64.so.2 /opt/hostabi/ && \
    ldd /opt/hostabi/AstraSim_BookSim2 | awk '/=> \// {print $3}' | sort -u | xargs -r -I{} cp -n {} /opt/hostabi/

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
FROM ${UBUNTU_IMAGE}

SHELL ["/bin/bash", "-c"]
ENV DEBIAN_FRONTEND=noninteractive

# Runtime dependencies only.
# NOTE: cmake + protobuf-compiler are REQUIRED here, not just in the
# builder: release.yml runs `make release-build` inside this image, and
# the ASTRA step needs protoc + cmake while Ramulator needs cmake.
# Guarded by scripts/check_release_toolchain.py.
RUN apt-get update && apt-get install -y --no-install-recommends \
    bison \
    ca-certificates \
    cmake \
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
    protobuf-compiler \
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
# Timeloop's bundled problem shapes (baked search path is /opt/timeloop) so
# students can reference predefined shapes; T3's own problem.yaml is self-contained
COPY --from=builder /opt/timeloop/problem-shapes /opt/timeloop/problem-shapes

# Environment: ASTRA-sim + Chakra + LLMServingSim on PYTHONPATH
ENV PYTHONPATH="/usr/local/share/chakra:/opt/llmservingsim:${PYTHONPATH}"

RUN ldconfig

ENV PYTHONPATH="/usr/local/share/yosys/python3:${PYTHONPATH}"

# Fix matplotlib/numpy compatibility (apt version compiled against numpy 1.x)
# Declared DSE runtime + release-test toolchain (pyproject [project]
# dependencies + release.yml pytest battery). scipy is REQUIRED:
# synthesis/milp_topology_v2.py and tools/deadlock_routing.py import it,
# so the old "remove apt scipy" behavior would break the MILP engine
# inside this image. Guarded by scripts/check_release_toolchain.py.
RUN pip3 install --upgrade --no-cache-dir 'matplotlib>=3.10' && \
    pip3 install --no-cache-dir \
        pydantic pyyaml fastapi uvicorn pytest scipy scikit-optimize

WORKDIR /workspace
CMD ["bash"]
