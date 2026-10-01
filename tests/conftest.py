import os

# Each child script otherwise allocates per-core BLAS buffers; parallel runs exhaust memory.
for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(name, "1")
