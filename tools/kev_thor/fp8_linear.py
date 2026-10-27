"""FP8 linears for the Thor's Blackwell tensor cores: e4m3 weights with one scale per output row (fixed at load), and
activations quantized per token on each call by one fused Triton kernel, multiplied with torch._scaled_mm into bf16."""
import torch
import triton
import triton.language as tl
from torch import nn

E4M3_MAX = torch.finfo(torch.float8_e4m3fn).max


@triton.jit
def _quant_rows(x_ptr, y_ptr, s_ptr, K, stride_x, stride_y, BLOCK: tl.constexpr):
    row = tl.program_id(0)
    offs = tl.arange(0, BLOCK)
    amax = tl.zeros([BLOCK], dtype=tl.float32)
    for k in range(0, K, BLOCK):
        m = offs + k < K
        v = tl.load(x_ptr + row * stride_x + k + offs, mask=m, other=0.0).to(tl.float32)
        amax = tl.maximum(amax, tl.abs(v))
    scale = tl.maximum(tl.max(amax, axis=0), 1e-12) / 448.0
    tl.store(s_ptr + row, scale)
    for k in range(0, K, BLOCK):
        m = offs + k < K
        v = tl.load(x_ptr + row * stride_x + k + offs, mask=m, other=0.0).to(tl.float32)
        tl.store(y_ptr + row * stride_y + k + offs, (v / scale).to(tl.float8e4nv), mask=m)


def quant_rows(x2: torch.Tensor):
    """x2 [M, K] bf16 -> (e4m3 [M, K], float32 scales [M, 1]), one scale per row."""
    M, K = x2.shape
    y = torch.empty((M, K), device=x2.device, dtype=torch.float8_e4m3fn)
    s = torch.empty((M, 1), device=x2.device, dtype=torch.float32)
    _quant_rows[(M,)](x2, y, s, K, x2.stride(0), y.stride(0), BLOCK=1024)
    return y, s


class FP8Linear(nn.Module):
    def __init__(self, linear: nn.Linear):
        super().__init__()
        w = linear.weight.detach()
        scale = w.abs().amax(dim=1, keepdim=True).float().clamp(min=1e-12) / E4M3_MAX          # [N, 1]
        self.register_buffer("w8", (w.float() / scale).to(torch.float8_e4m3fn).contiguous())  # [N, K]; w8.t() is the column-major [K, N] _scaled_mm wants
        self.register_buffer("w_scale", scale.t().contiguous())                                # [1, N]
        self.bias = linear.bias
        self.out_features, self.in_features = w.shape

    def forward(self, x):
        shape = x.shape
        a8, a_scale = quant_rows(x.reshape(-1, shape[-1]).contiguous())
        y = torch._scaled_mm(a8, self.w8.t(), scale_a=a_scale, scale_b=self.w_scale, out_dtype=torch.bfloat16)
        if self.bias is not None:
            y = y + self.bias
        return y.reshape(*shape[:-1], self.out_features)


def to_fp8(module: nn.Module, skip=("embed", "lm_head")) -> int:
    """Replace every nn.Linear under `module` (except names containing `skip`) in place; returns how many."""
    n = 0
    for name, child in list(module.named_children()):
        if any(s in name for s in skip):
            continue
        if isinstance(child, nn.Linear) and child.in_features % 16 == 0 and child.out_features % 16 == 0:
            setattr(module, name, FP8Linear(child))
            del child
            n += 1
        else:
            n += to_fp8(child, skip)
    return n
