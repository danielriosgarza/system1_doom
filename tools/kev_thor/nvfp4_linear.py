"""NVFP4 linears for Blackwell's 4-bit tensor cores: e2m1 values in blocks of 16 along K with one e4m3 scale per block
and one fp32 scale per tensor, for the weights (at load) and the activations (per call, one Triton kernel), multiplied
by torch.nn.functional.scaled_mm into bf16. The block scales are written in cuBLAS's 128x4 tile layout (SWIZZLE_32_4_4)."""
import torch
import torch.nn.functional as F
import triton
import triton.language as tl
from torch import nn
from torch.nn.functional import ScalingType, SwizzleType

E2M1_MAX, E4M3_MAX = 6.0, 448.0
BK = 256  # activation elements per program: 16 blocks of 16


def _rup(x, m):
    return (x + m - 1) // m * m


@triton.jit
def _quant_nvfp4(x_ptr, q_ptr, s_ptr, g_ptr, K, stride_x, n_col_blocks, BK: tl.constexpr):
    row = tl.program_id(0)
    kb = tl.program_id(1)
    offs = kb * BK + tl.arange(0, BK)
    x = tl.load(x_ptr + row * stride_x + offs, mask=offs < K, other=0.0).to(tl.float32)
    g = tl.load(g_ptr)
    xb = tl.reshape(x, [BK // 16, 16])
    s8 = tl.minimum(tl.max(tl.abs(xb), axis=1) / 6.0 / g, 448.0).to(tl.float8e4nv)
    sf = s8.to(tl.float32) * g
    q = xb / tl.where(sf > 0, sf, 1.0)[:, None]
    q = tl.minimum(tl.maximum(q, -6.0), 6.0)
    a = tl.abs(q)
    code = ((a > 0.25).to(tl.uint8) + (a > 0.75).to(tl.uint8) + (a > 1.25).to(tl.uint8) + (a > 1.75).to(tl.uint8)
            + (a > 2.5).to(tl.uint8) + (a > 3.5).to(tl.uint8) + (a > 5.0).to(tl.uint8))
    code = code | ((q < 0).to(tl.uint8) << 3)
    lo, hi = tl.split(tl.reshape(code, [BK // 2, 2]))
    tl.store(q_ptr + row * (K // 2) + kb * (BK // 2) + tl.arange(0, BK // 2), lo | (hi << 4), mask=kb * (BK // 2) + tl.arange(0, BK // 2) < K // 2)
    col = kb * (BK // 16) + tl.arange(0, BK // 16)
    ri = row % 128
    off = ((row // 128) * n_col_blocks + col // 4) * 512 + (ri % 32) * 16 + (ri // 32) * 4 + col % 4
    tl.store(s_ptr + off, s8, mask=col < K // 16)


def quantize_activations(x2: torch.Tensor):
    """x2 [M, K] bf16 (K a multiple of 64) -> (e2m1 [M, K/2], blocked e4m3 scales, fp32 global scale)."""
    M, K = x2.shape
    g = (x2.abs().amax().float().clamp(min=1e-12) / (E2M1_MAX * E4M3_MAX)).reshape(())
    q = torch.empty((M, K // 2), device=x2.device, dtype=torch.uint8)
    n_col_blocks = _rup(K // 16, 4) // 4
    s = torch.zeros(_rup(M, 128) * n_col_blocks * 4, device=x2.device, dtype=torch.float8_e4m3fn)
    _quant_nvfp4[(M, triton.cdiv(K, BK))](x2, q, s, g, K, x2.stride(0), n_col_blocks, BK=BK)
    return q.view(torch.float4_e2m1fn_x2), s, g


def _to_blocked(scales: torch.Tensor) -> torch.Tensor:
    rows, cols = scales.shape
    R, C = _rup(rows, 128), _rup(cols, 4)
    padded = torch.zeros((R, C), dtype=scales.dtype, device=scales.device)
    padded[:rows, :cols] = scales
    return padded.view(R // 128, 128, C // 4, 4).permute(0, 2, 1, 3).reshape(-1, 4, 32, 4).transpose(1, 2).reshape(-1, 32, 16).flatten()


def quantize_weight(w: torch.Tensor):
    """w [N, K] -> (e2m1 [N, K/2], blocked e4m3 scales, fp32 global scale), in torch ops (once, at load)."""
    N, K = w.shape
    wf = w.float()
    g = (wf.abs().amax().clamp(min=1e-12) / (E2M1_MAX * E4M3_MAX)).reshape(())
    blocks = wf.view(N, K // 16, 16)
    bs = (blocks.abs().amax(-1) / E2M1_MAX / g).clamp(max=E4M3_MAX).to(torch.float8_e4m3fn)
    denom = (bs.float() * g).unsqueeze(-1)
    q = torch.where(denom > 0, blocks / denom, torch.zeros_like(blocks)).clamp(-E2M1_MAX, E2M1_MAX).view(N, K)
    edges = torch.tensor([0.25, 0.75, 1.25, 1.75, 2.5, 3.5, 5.0], device=w.device)
    code = torch.bucketize(q.abs(), edges).to(torch.uint8) | ((q < 0).to(torch.uint8) << 3)
    packed = (code[:, 0::2] | (code[:, 1::2] << 4)).contiguous()
    return packed.view(torch.float4_e2m1fn_x2), _to_blocked(bs), g


class NVFP4Linear(nn.Module):
    def __init__(self, linear: nn.Linear):
        super().__init__()
        q, s, g = quantize_weight(linear.weight.detach())
        self.register_buffer("w4", q)
        self.register_buffer("w_scale", s)
        self.register_buffer("w_global", g)
        self.bias = linear.bias
        self.out_features, self.in_features = linear.weight.shape

    def forward(self, x):
        shape = x.shape
        a4, a_scale, a_global = quantize_activations(x.reshape(-1, shape[-1]).contiguous())
        y = F.scaled_mm(a4, self.w4.t(), [a_scale, a_global], [ScalingType.BlockWise1x16, ScalingType.TensorWise],
                        [self.w_scale, self.w_global], [ScalingType.BlockWise1x16, ScalingType.TensorWise],
                        swizzle_a=[SwizzleType.SWIZZLE_32_4_4, SwizzleType.NO_SWIZZLE],
                        swizzle_b=[SwizzleType.SWIZZLE_32_4_4, SwizzleType.NO_SWIZZLE], output_dtype=torch.bfloat16)
        if self.bias is not None:
            y = y + self.bias
        return y.reshape(*shape[:-1], self.out_features)


def to_nvfp4(module: nn.Module, skip=("embed", "lm_head")) -> int:
    n = 0
    for name, child in list(module.named_children()):
        if any(s in name for s in skip):
            continue
        if isinstance(child, nn.Linear) and child.in_features % 64 == 0 and child.out_features % 16 == 0:
            setattr(module, name, NVFP4Linear(child))
            del child
            n += 1
        else:
            n += to_nvfp4(child, skip)
    return n


if __name__ == "__main__":
    # The Triton activation path against the torch weight path on the same matrix: identical codes and scales.
    torch.manual_seed(0)
    x = (torch.randn(300, 5120, device="cuda") * 3).to(torch.bfloat16)
    qa, sa, ga = quantize_activations(x)
    qw, sw, gw = quantize_weight(x)
    print("codes equal:", torch.equal(qa.view(torch.uint8), qw.view(torch.uint8)),
          "| scales equal:", torch.equal(sa.view(torch.uint8), sw.view(torch.uint8)), "| global equal:", torch.allclose(ga, gw))
    w = (torch.randn(1024, 5120, device="cuda") * 0.02).to(torch.bfloat16)
    lin = nn.Linear(5120, 1024, bias=False, device="cuda", dtype=torch.bfloat16); lin.weight.data = w
    y4 = NVFP4Linear(lin)(x).float(); y = lin(x).float()
    print("NVFP4Linear vs bf16: cosine per row min %.4f mean %.4f" % (F.cosine_similarity(y4, y, -1).min(), F.cosine_similarity(y4, y, -1).mean()))
