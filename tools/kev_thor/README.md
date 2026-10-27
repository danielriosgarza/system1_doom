# Kev on a Jetson Thor

`serve_thor.py` runs Kev's own server (`python -m kev.serve` from
[github.com/jaredpalmer/kev](https://github.com/jaredpalmer/kev)) with two changes for the
Jetson Thor's Blackwell GPU (sm_110), so the rule tree can use Kev-27B with `--decider kev`
(docs/DOCUMENTATION.md §15):

- **Kev's fused kernels on flash-linear-attention 0.6.0.** Kev refuses any version but 0.5.2
  and patches 0.5.2's kernel launches; 0.6.0's kernels do not take the patched argument, so the
  patch is skipped. The fused path also replaces the slow PyTorch causal convolution that runs
  without the `causal_conv1d` package.
- **Low-precision projections** on the Thor's tensor cores, chosen with `KEV_QUANT`:
  `fp8` (`fp8_linear.py`: e4m3 weights with a scale per output row, activations per token),
  `nvfp4-mlp` (the default: the MLP projections NVFP4, `nvfp4_linear.py`, e2m1 in blocks of 16
  with e4m3 block scales and the activations quantized by one Triton kernel; the mixers' FP8),
  `nvfp4` (every projection NVFP4) or `bf16`.

Measured on the Thor (MAXN, JetPack 7.1, torch 2.14.1+cu130, Kev-27B `v1.0`). On this GPU bf16
matrix multiplies reach about 92 TFLOPS, FP8 about 190, and NVFP4 about twice FP8 at Kev's
shapes; memory moves at about 221 GB/s.

| | As installed | Fused | Fused, FP8 | Fused, NVFP4 MLPs |
|---|---:|---:|---:|---:|
| Backbone, one 745-token state as a CUDA graph | 756 ms | 570 ms | 337 ms | 302 ms |
| Server: a question about a new state (median) | 1,093 ms | | 498 ms | 462 ms |
| Server: another question about the same state (median) | 339 ms | | 170 ms | 151 ms |
| Weights in memory | 51 GB | 51 GB | 27 GB | 20 GB |
| Same pick as installed, of 709 rule-tree questions | | | 707 | 706 |
| Right, of the 561 the state text settles | 561 | | 561 | 560 |

Every projection in NVFP4 (17 GB) took the last hidden state to a cosine of 0.96 against bf16 at
its worst token, so it is not the default.

Kev pins torch below 2.9, which has no CUDA 13 build for the Thor, so install it with an
override:

```bash
git clone https://github.com/jaredpalmer/kev.git && cd kev
echo "torch>=2.10" > overrides.txt && uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e ".[serve]" flash-linear-attention --override overrides.txt
KEV_PREFIX_CACHE=16 .venv/bin/python <this repository>/tools/kev_thor/serve_thor.py \
    --run jaredpalmer/kev-27b@v1.0 --host 127.0.0.1 --port 8008
```
