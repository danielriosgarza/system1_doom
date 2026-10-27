"""kev.serve tuned for the Jetson Thor (Blackwell, sm_110): Kev's fused kernels on the installed flash-linear-attention,
and low-precision projections on the Thor's FP8 and FP4 tensor cores.

    cd <a clone of github.com/jaredpalmer/kev, with its environment> && \
        .venv/bin/python <this repository>/tools/kev_thor/serve_thor.py --run jaredpalmer/kev-27b@v1.0 --port 8008

KEV_QUANT picks the projections' precision (the embeddings stay as they are):
  bf16       Kev's own (fused kernels only)
  fp8        every projection FP8 (e4m3 weights with a scale per output row, activations per token)
  nvfp4-mlp  the MLP projections NVFP4 (e2m1 in blocks of 16 with e4m3 block scales), the mixers' FP8 (the default)
  nvfp4      every projection NVFP4

Kev-27B's backbone on this Thor, one state replayed as a CUDA graph (745 tokens / 64 tokens), and memory:
  as kev.serve runs it here (unfused bf16)  756 ms            51 GB
  bf16, fused                               570 / 257 ms      51 GB
  fp8                                       337 ms            27 GB
  nvfp4-mlp                                 302 / 100 ms      20 GB
  nvfp4                                     316 / 90 ms       17 GB
On this GPU bf16 matmuls reach about 92 TFLOPS, FP8 about 190, NVFP4 about twice FP8 at Kev's shapes; a pass over a
short question is bound by reading the weights (about 221 GB/s), which is why the 4-bit weights help it most.

Kev's fused kernels refuse any flash-linear-attention but 0.5.2 and patch 0.5.2's kernel launches (_fix_nb); 0.6.0's
kernels no longer take that argument, so the patch is skipped (the fused pass matched the reference to a cosine of 0.9998
on the last hidden state). Check answers on your own questions before relying on a lower precision.
"""
import os
import sys

import torch
import torch.nn.functional as TF
from torch import nn

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("KEV_FUSED", "1")

import fla  # noqa: E402
import kev.fused_qwen35 as fq  # noqa: E402
from fp8_linear import FP8Linear, to_fp8  # noqa: E402
from nvfp4_linear import NVFP4Linear, to_nvfp4  # noqa: E402

QUANTS = ("bf16", "fp8", "nvfp4-mlp", "nvfp4")
QUANT = os.environ.get("KEV_QUANT", "nvfp4-mlp")
if QUANT not in QUANTS:
    raise SystemExit(f"KEV_QUANT={QUANT!r}: one of {', '.join(QUANTS)}")

fq.FLA_VERSION = fla.__version__
fq._fix_nb = lambda: None


class _F:
    """torch.nn.functional for kev.fused_qwen35, whose fused projections are bare weights given to F.linear: a
    quantized projection in their place is called as a module."""

    def __getattr__(self, name):
        return getattr(TF, name)

    def linear(self, x, w, b=None):
        return w(x) if isinstance(w, nn.Module) else TF.linear(x, w, b)


def _wrap(weight: torch.Tensor, cls):
    linear = nn.Linear(weight.shape[1], weight.shape[0], bias=False, device=weight.device, dtype=weight.dtype)
    linear.weight = nn.Parameter(weight, requires_grad=False)
    return cls(linear)


if QUANT != "bf16":
    _fuse = fq.fuse
    mixer_cls = NVFP4Linear if QUANT == "nvfp4" else FP8Linear
    mlp_cls = FP8Linear if QUANT == "fp8" else NVFP4Linear

    @torch.no_grad()
    def fuse_quantized(lm):
        _fuse(lm)
        for layer in lm.layers:
            mixer = layer.linear_attn if layer.block_type == "linear_attention" else layer.self_attn
            for name in ("in_proj", "qkv"):
                if isinstance(getattr(mixer, name, None), torch.Tensor):
                    setattr(mixer, name, _wrap(getattr(mixer, name), mixer_cls))
            layer.mlp.gate_up = _wrap(layer.mlp.gate_up, mlp_cls)
            layer.mlp.down_proj = mlp_cls(layer.mlp.down_proj)
        n = (to_nvfp4 if QUANT == "nvfp4" else to_fp8)(lm)   # what is left: the mixers' output projections
        torch.cuda.empty_cache()
        print(f"kev-thor: fused kernels on flash-linear-attention {fla.__version__}, projections {QUANT} "
              f"({n} output projections {mixer_cls.__name__})", flush=True)
        return lm

    fq.fuse = fuse_quantized
    fq.F = _F()

import kev.serve  # noqa: E402

if __name__ == "__main__":
    sys.exit(kev.serve.main())
