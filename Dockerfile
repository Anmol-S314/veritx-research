# Stage 1: Build all VeritX research tools
FROM ubuntu:22.04 AS builder

LABEL description="VeritX Research Tools — Booksim, Timeloop, Accelergy (T4 formal tools Yosys/SymbiYosys/CBMC temporarily disabled — see below)"

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
# T4 FORMAL TOOLS (Yosys, SymbiYosys, CBMC) — TEMPORARILY DISABLED.
#
# These three source builds are ~80% of the image build time (~35 min). T4 is
# not active right now, so they are commented out to keep builds fast. To bring
# the formal track back: uncomment these blocks, re-add `t4-formal` to the CI
# matrix and the `sim-t4-formal` job in .gitlab-ci.yml, then rebuild.
#
# # Yosys (T4)
# RUN pip3 install cmake && \
#     git clone --depth 1 --recurse-submodules --shallow-submodules \
#         https://github.com/YosysHQ/yosys.git && \
#     cd yosys && \
#     mkdir build && cd build && \
#     cmake .. -DBUILD_EDA=ON -DENABLE_READLINE=OFF -DWITH_ABC=OFF \
#         -DCMAKE_INSTALL_PREFIX=/usr/local && \
#     make -j$(nproc) && \
#     make install && \
#     cp -r /opt/yosys/backends/smt2/smtio.py /usr/local/share/yosys/python3/ && \
#     strip /usr/local/bin/yosys
#
# # SymbiYosys (T4)
# RUN git clone --depth 1 https://github.com/YosysHQ/sby.git && \
#     cd sby && \
#     make install && \
#     mkdir -p /usr/local/share/yosys/python3/ && \
#     cp sbysrc/*.py /usr/local/share/yosys/python3/
#
# # CBMC (T4)
# RUN git clone --depth 1 https://github.com/diffblue/cbmc.git && \
#     cd cbmc && \
#     cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DWITH_JBMC=OFF && \
#     cmake --build build -j$(nproc) && \
#     cmake --install build && \
#     strip /usr/local/bin/cbmc

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

# Ordered by volatility: Yosys/SymbiYosys/CBMC and Timeloop are pinned and
# effectively frozen, so they go first and stay cached. Accelergy's backends
# churn more (new estimator, new node), and booksim-ext/ churns most of all —
# so they sit at the bottom. A layer change invalidates everything BELOW it,
# never above, which is what makes a targeted rebuild possible at all.
# =============================================================================
# Accelergy (T3 — Topology energy estimation)
# =============================================================================
RUN git clone --depth 1 https://github.com/Accelergy-Project/accelergy.git && \
    cd accelergy && \
    pip3 install .

# Accelergy estimation backends. Core alone ships no real estimator, so every
# ERT/ART it emits is a placeholder. Accelergy runs an auction: each plugin bids
# an accuracy for a (component, action) query and the highest bid wins.
#
# Aladdin (accuracy 70) — wire, crossbar, comparator, FIFO, intadder. 40/45nm only.
# `wire` energy is analytic; the rest are CSV lookups that REQUIRE an
# `action_latency_cycles` action argument or they raise KeyError.
RUN git clone --depth 1 https://github.com/Accelergy-Project/accelergy-aladdin-plug-in.git && \
    cd accelergy-aladdin-plug-in && \
    pip3 install .

# CACTI — SRAM/DRAM only, but the sole backend with modern nodes (22/32/45/65/90nm,
# interpolated). `cacti/` is a submodule, hence --recurse-submodules. Its makefile
# passes -gstabs+ (dropped in GCC 12) and -m64 (breaks arm64); upstream ships
# cacti.patch for exactly this. `make` must precede pip install — it builds the
# `cacti` binary that the Python wrapper shells out to.
RUN git clone --depth 1 --recurse-submodules --shallow-submodules \
        https://github.com/Accelergy-Project/accelergy-cacti-plug-in.git && \
    cd accelergy-cacti-plug-in && \
    sed -i 's/ -gstabs+//; s/g++ -m64/g++/; s/gcc -m64/gcc/' cacti/cacti.mk && \
    make && \
    pip3 install .

# Library (bids 90 on a table hit, 0 otherwise) — successor to the table-based
# plug-in, which now prints "DEPRECATED. Use the Library plug-in instead."
# Ships citable literature tables, incl. `isaac_router` (32nm, 256b, 20.74 pJ,
# 150000 um^2) and `isaac_chip2chip_link` — the only shipped router/link numbers
# at a modern node; Aladdin's wire/crossbar stop at 40/45nm.
#
# It is also the bring-your-own-numbers backend: a component class is just a CSV
# filename under .../accelergy-library-plugin/<set>/<class>.csv, so a `router.csv`
# at your node defines a `router` class. That is how you price a NoC Aladdin can't.
RUN git clone --depth 1 https://github.com/Accelergy-Project/accelergy-library-plug-in.git && \
    cd accelergy-library-plug-in && \
    pip3 install .

# Drop Accelergy's built-in `dummy` estimator. It is not a backend — it answers
# 1 pJ / 1 um^2 to every query, and Accelergy falls back to it *silently* (INFO
# log, exit 0) whenever a real plugin bids and then raises. That is how the
# eyeriss reference ERT came to read 15.016 pJ: 13.016 from Aladdin's wire plus
# two comparators at a fabricated 1.0 each. Without dummy, that same input exits
# 1 and emits nothing. A component no backend can price must fail loudly.
RUN rm -rf /usr/local/share/accelergy/estimation_plug_ins/dummy_tables

# =============================================================================
# Booksim 2.0 + VeritX extensions (T2, T3 — Deadlock, Topology)
#
# DELIBERATELY LAST in the builder stage. Docker invalidates every layer after a
# changed one, and Booksim is the only source people here actually edit. Keeping it
# at the bottom means Accelergy, Timeloop, Yosys, SymbiYosys and CBMC above it stay
# cached when a .cpp changes.
#
# Booksim is VENDORED as a git subtree at third_party/booksim2 — pinned upstream with
# VeritX's edits carried as ordinary commits on top (see third_party/booksim2/VERITX.md).
# No clone, no patch, no overlay: you edit the real .cpp files with full LSP, `git diff`
# shows exactly our delta, and an upstream bump is a `git subtree pull` merge. The image
# just copies the tree and builds it — editing a Booksim file invalidates only this COPY
# + the compile (~1-2 min), never the layers above.
# =============================================================================
COPY third_party/booksim2/ /opt/booksim2/
RUN cd /opt/booksim2/src && make -j$(nproc) && cp booksim /usr/local/bin/

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
