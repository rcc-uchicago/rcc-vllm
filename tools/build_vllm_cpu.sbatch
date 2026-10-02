#!/bin/bash
# Build vLLM 0.26.0 for CPU (VLLM_TARGET_DEVICE=cpu) into
# /project/rcc/mehta5/conda-envs/vllm-cpu.
#
# Why a source build: vLLM's prebuilt CPU wheels are manylinux_2_35; midway3 is
# glibc 2.28, so they will not install. Built on an `amd` node (EPYC 7702, AVX2,
# no AVX512) so the build host matches the run host; 0.26.0 compiles both the
# AVX2 and AVX512 kernel sets and dispatches at runtime.
#
# CPU-only job: no GPU, no billing. Name follows the mrefresh-nest fence.
#SBATCH --job-name=mrefresh-nest-build-vllm-cpu
#SBATCH --partition=amd
#SBATCH --qos=amd
#SBATCH --account=rcc-staff
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=32
#SBATCH --mem=64G
#SBATCH --time=03:00:00
#SBATCH --output=/project/rcc/mehta5/vllm/logs/build-vllm-cpu-%j.out
set -euo pipefail

ENV=/project/rcc/mehta5/conda-envs/vllm-cpu
SRC=/project/rcc/mehta5/build/vllm-0.26.0

module load python/miniforge-25.3.0 gcc/13.2.0
eval "$(mamba shell hook --shell bash)"
[ -d "$ENV" ] || mamba create -y -p "$ENV" python=3.12
mamba activate "$ENV"
# el8's system assembler (binutils 2.30) does not know AVX512-BF16/AMX
# (vcvtneps2bf16, ldtilecfg) used by vLLM's AVX512 kernels -- build 59856519
# died on exactly that. The /software gcc ships no `as`, so it takes the first
# one on PATH. Shim ONLY `as` from a separate binutils env: conda's `ld` links
# against its sysroot libdl (newer glibc) and breaks every OpenMP link test
# (__libc_dlerror_result@GLIBC_PRIVATE, build 59857171), so `ld` stays /usr/bin.
BINUTILS=/project/rcc/mehta5/conda-envs/binutils-new
[ -x "$BINUTILS/bin/as" ] || mamba create -y -p "$BINUTILS" -c conda-forge "binutils>=2.40"
SHIM=/tmp/${USER}_${SLURM_JOB_ID}_asbin; mkdir -p "$SHIM"
ln -sf "$BINUTILS/bin/as" "$SHIM/as"
export PATH="$SHIM:$PATH"
hash -r; as --version | head -1; ld --version | head -1

# csrc/cpu/utils.cpp needs numa.h + libnuma; el8 nodes ship neither the headers
# nor numactl-devel (build 59857250). Take them from conda-forge into the env.
mamba install -y -p "$ENV" -c conda-forge libnuma
export CPATH="$ENV/include${CPATH:+:$CPATH}"
export LIBRARY_PATH="$ENV/lib${LIBRARY_PATH:+:$LIBRARY_PATH}"
export LD_LIBRARY_PATH="$ENV/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

export TMPDIR=/tmp/${USER}_${SLURM_JOB_ID}; mkdir -p "$TMPDIR"
export CC=$(which gcc) CXX=$(which g++)
export MAX_JOBS=${SLURM_CPUS_PER_TASK}
export VLLM_TARGET_DEVICE=cpu
# as 2.46 compresses .debug_* sections in a format ld 2.30 cannot read ("unable to
# initialize decompress status", build 59857405). Build without debug info, and
# tell the assembler not to compress in case any target still emits -g.
export CMAKE_BUILD_TYPE=Release
# /software gcc-13.2.0 defaults to -mstack-protector-guard=global, so oneDNN's
# -fstack-protector-strong objects reference __stack_chk_guard, which x86_64 glibc
# does not export ("undefined symbol: __stack_chk_guard" on import, build 59857627).
# Force the normal x86_64 TLS guard.
SSP="-mstack-protector-guard=tls"
export CFLAGS="${CFLAGS:-} -Wa,--compress-debug-sections=none ${SSP}"
export CXXFLAGS="${CXXFLAGS:-} -Wa,--compress-debug-sections=none ${SSP}"

cd "$SRC"
pip install --upgrade pip
pip install -r requirements/build/cpu.txt --extra-index-url https://download.pytorch.org/whl/cpu
pip install -r requirements/cpu.txt --extra-index-url https://download.pytorch.org/whl/cpu
pip install . --no-build-isolation -v 2>&1 | tail -400

cd "$TMPDIR"
# Import check WITHOUT the build's LD_LIBRARY_PATH beyond env/lib -- this is the
# exact runtime the launcher gives the serve job (gcc-13 libstdc++ from env/lib).
export LD_LIBRARY_PATH="$ENV/lib"
# Load the kernels the way vLLM does (platforms/cpu.py picks _C_AVX512 or _C_AVX2
# by CPU flags; both register module _C). Importing vllm._C directly is the
# AVX512 build and dies with SIGILL on the AVX2-only amd nodes.
python -c "from vllm.platforms import current_platform as p; import torch; p.import_kernels(); print('kernels ok', torch.ops._C.rms_norm)"
python -c "import vllm, torch; print('vllm', vllm.__version__, 'torch', torch.__version__)"
python -c "from vllm.platforms import current_platform as p; print('platform', p.device_type)"
echo BUILD_OK
