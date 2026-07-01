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
# Booksim 2.0 + VeritX matrix traffic pattern (T2, T3 — Deadlock, Topology)
# Pinned commit + the `matrix(<file>)` pattern that feeds a Timeloop traffic
# matrix into Booksim (the Timeloop->Booksim bridge for T3). Source kept at
# /opt/booksim2 so students can add custom patterns/topologies and recompile.
# =============================================================================
COPY tracks/t3-topology/booksim-ext/ /opt/booksim-ext/
RUN git clone https://github.com/booksim/booksim2.git && \
    cd booksim2 && git checkout 28f43299f1706a3160ffac721ca461d74eb6e618 && \
    cp /opt/booksim-ext/matrixtraffic.hpp /opt/booksim-ext/matrixtraffic.cpp src/ && \
    git apply /opt/booksim-ext/matrix_traffic.patch && \
    cd src && make -j$(nproc) && \
    cp booksim /usr/local/bin/

# =============================================================================
# Accelergy (T3 — Topology energy estimation)
# =============================================================================
RUN git clone --depth 1 https://github.com/Accelergy-Project/accelergy.git && \
    cd accelergy && \
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
# Yosys (T4 — Formal Verification)
# =============================================================================
RUN pip3 install cmake && \
    git clone --depth 1 --recurse-submodules --shallow-submodules \
        https://github.com/YosysHQ/yosys.git && \
    cd yosys && \
    mkdir build && cd build && \
    cmake .. -DBUILD_EDA=ON -DENABLE_READLINE=OFF -DWITH_ABC=OFF \
        -DCMAKE_INSTALL_PREFIX=/usr/local && \
    make -j$(nproc) && \
    make install && \
    # CMake may miss some share files; copy them explicitly
    cp -r /opt/yosys/backends/smt2/smtio.py /usr/local/share/yosys/python3/ && \
    strip /usr/local/bin/yosys

# =============================================================================
# SymbiYosys (T4)
# =============================================================================
RUN git clone --depth 1 https://github.com/YosysHQ/sby.git && \
    cd sby && \
    make install && \
    mkdir -p /usr/local/share/yosys/python3/ && \
    cp sbysrc/*.py /usr/local/share/yosys/python3/

# =============================================================================
# CBMC (T4)
# =============================================================================
RUN git clone --depth 1 https://github.com/diffblue/cbmc.git && \
    cd cbmc && \
    cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DWITH_JBMC=OFF && \
    cmake --build build -j$(nproc) && \
    cmake --install build && \
    strip /usr/local/bin/cbmc

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
    wget \
    z3 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local/bin/ /usr/local/bin/
COPY --from=builder /usr/local/lib/ /usr/local/lib/
COPY --from=builder /usr/local/share/ /usr/local/share/
COPY --from=builder /usr/lib/python3/dist-packages/ /usr/lib/python3/dist-packages/
# Booksim source (with matrix pattern) so students can extend + recompile
COPY --from=builder /opt/booksim2 /opt/booksim2
# Timeloop's bundled problem shapes (baked search path is /opt/timeloop) so
# students can reference predefined shapes; T3's own problem.yaml is self-contained
COPY --from=builder /opt/timeloop/problem-shapes /opt/timeloop/problem-shapes

RUN ldconfig

ENV PYTHONPATH="/usr/local/share/yosys/python3:${PYTHONPATH}"

# Fix matplotlib/numpy compatibility (apt version compiled against numpy 1.x)
# Remove apt scipy (ABI-incompatible with numpy 2.x); none of our tracks use it
RUN pip3 install --upgrade --no-cache-dir 'matplotlib>=3.10' && \
    pip3 uninstall -y scipy 2>/dev/null; \
    rm -rf /usr/lib/python3/dist-packages/scipy* /usr/lib/python3/dist-packages/scipy/ 2>/dev/null; true

WORKDIR /workspace
CMD ["bash"]
