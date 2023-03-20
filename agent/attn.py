import torch
import torch.nn as nn
import torch.nn.functional as F
from params import *

class Attn(nn.Module):
    """
    Attention for weighting state features
    """
    def __init__(self, state_dim, embed_dim, num_heads):
        super().__init__()
        self.state_dim = state_dim
        self.embed_dim = embed_dim
        self.num_heads = num_heads
        self.project_layer = nn.Linear(self.state_dim, self.embed_dim)
        self.ctx_layers = []
        for _ in range(self.state_dim):
            self.ctx_layers.append(nn.Linear(self.state_dim, self.embed_dim))
        self.attn = nn.MultiheadAttention(self.embed_dim, self.num_heads, dropout=0.2, batch_first=True)
        self.scale = 1.0 / (self.embed_dim ** 0.5)

    def forward(self, x):
        if USE_ATTN:
            q = self.project_layer(x)
            q = ACTIVATION(q)
            # print("q: {}".format(q.shape))
            k = []
            for ctx in self.ctx_layers:
                k.append(ctx(x))
            k = torch.cat(k, dim=1)
            k = ACTIVATION(k)
            k = F.normalize(k, p=2.0, dim=1)
            # print(k)
            # print("k: {}".format(k.shape))
            v = k
            # print("v: {}".format(v.shape))
            output, weights = self.attn(q, k, v)
            # print(weights)
        else:
            output = x
            weights = None
        return output, weights
