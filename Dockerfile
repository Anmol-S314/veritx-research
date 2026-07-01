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
# Booksim 2.0 (T2, T3 — Deadlock, Topology)
# =============================================================================
RUN git clone --depth 1 https://github.com/booksim/booksim2.git && \
    cd booksim2/src && \
    make -j$(nproc) && \
    cp booksim /usr/local/bin/ && \
    strip /usr/local/bin/booksim

# =============================================================================
# Accelergy (T3 — Topology energy estimation; Timeloop added later via scons)
# =============================================================================
RUN git clone --depth 1 https://github.com/Accelergy-Project/accelergy.git && \
    cd accelergy && \
    pip3 install .

# =============================================================================
# Yosys (T4 — Formal Verification)
# =============================================================================
RUN pip3 install cmake && \
    git clone --depth 1 --recurse-submodules --shallow-submodules \
        https://github.com/YosysHQ/yosys.git && \
    cd yosys && \
    mkdir build && cd build && \
    cmake .. -DBUILD_EDA=ON -DENABLE_READLINE=OFF -DWITH_ABC=OFF && \
    make -j$(nproc) && \
    make install && \
    strip /usr/local/bin/yosys && \
    cd /opt && rm -rf yosys

# =============================================================================
# SymbiYosys (T4)
# =============================================================================
RUN git clone --depth 1 https://github.com/YosysHQ/sby.git && \
    cd sby && \
    make install && \
    mkdir -p /usr/local/share/yosys/python3/ && \
    cp sbysrc/sby_*.py /usr/local/share/yosys/python3/

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

# Fix matplotlib/numpy compatibility (apt version compiled against numpy 1.x)
RUN pip3 install --upgrade --no-cache-dir 'matplotlib>=3.10'

WORKDIR /workspace
CMD ["bash"]
