# Stage 1: Build all VeritX research tools
FROM ubuntu:22.04 AS builder

LABEL description="VeritX Research Tools — gem5, Booksim, Timeloop, Accelergy, Yosys, SymbiYosys, CBMC"

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
    libgoogle-perftools-dev \
    libprotobuf-dev \
    make \
    mercurial \
    ninja-build \
    pkg-config \
    protobuf-compiler \
    python3 \
    python3-dev \
    python3-numpy \
    python3-matplotlib \
    python3-pip \
    python3-tk \
    swig \
    wget \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt

# =============================================================================
# gem5 (T1 — KVCache QoS)
# =============================================================================
RUN git clone --depth 1 https://github.com/gem5/gem5.git && \
    cd gem5 && \
    scons build/X86/gem5.opt --ignore-style -j$(nproc) && \
    strip build/X86/gem5.opt

# =============================================================================
# Booksim 2.0 (T2, T3 — Deadlock, Topology)
# =============================================================================
RUN git clone --depth 1 https://github.com/booksim/booksim2.git && \
    cd booksim2 && \
    make -j$(nproc) && \
    cp booksim /usr/local/bin/ && \
    strip /usr/local/bin/booksim

# =============================================================================
# Timeloop + Accelergy (T3 — Topology)
# =============================================================================
RUN git clone --depth 1 https://github.com/Accelergy-Project/timeloop.git && \
    cd timeloop && \
    pip3 install -e . && \
    cd /opt && \
    git clone --depth 1 https://github.com/Accelergy-Project/accelergy.git && \
    cd accelergy && \
    pip3 install -e .

# =============================================================================
# Yosys + SymbiYosys + CBMC (T4 — Formal Verification)
# =============================================================================
RUN git clone --depth 1 https://github.com/YosysHQ/yosys.git && \
    cd yosys && \
    make -j$(nproc) && \
    make install && \
    strip /usr/local/bin/yosys && \
    cd /opt && \
    git clone --depth 1 https://github.com/YosysHQ/sby.git && \
    cd sby && \
    make install && \
    cd /opt && \
    git clone --depth 1 https://github.com/diffblue/cbmc.git && \
    cd cbmc && \
    cmake -S . -B build -DCMAKE_BUILD_TYPE=Release && \
    cmake --build build -j$(nproc) && \
    cmake --install build && \
    strip /usr/local/bin/cbmc

# =============================================================================
# Python dependencies (shared across all tracks)
# =============================================================================
RUN pip3 install --no-cache-dir \
    pandas \
    seaborn \
    jupyter \
    click \
    pyyaml

# Cleanup build artifacts
RUN rm -rf /opt/gem5 /opt/booksim2 /opt/timeloop /opt/accelergy /opt/yosys /opt/sby /opt/cbmc \
    /root/.cache /tmp/*

# =============================================================================
# Stage 2: Runtime image (slim)
# =============================================================================
FROM ubuntu:22.04

SHELL ["/bin/bash", "-c"]
ENV DEBIAN_FRONTEND=noninteractive

# Runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    git \
    libgoogle-perftools4 \
    libprotobuf-dev \
    make \
    python3 \
    python3-numpy \
    python3-matplotlib \
    python3-pip \
    python3-tk \
    wget \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local/bin/ /usr/local/bin/
COPY --from=builder /usr/local/lib/ /usr/local/lib/
COPY --from=builder /usr/lib/python3/dist-packages/ /usr/lib/python3/dist-packages/

RUN ldconfig

WORKDIR /workspace
CMD ["bash"]
