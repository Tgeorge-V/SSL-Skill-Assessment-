# -*- coding: utf-8 -*-
import math
import numpy as np
import torch
import torch.nn as nn
from ipdb import set_trace
import random
import torch.nn.functional as F
from transformer import SnippetEmbedding, SingleStageTCN, SingleStageTCN_new, SingleStageTCN_new1

class TemporalShift(nn.Module):
    def __init__(self, n_segment=3, n_div=8, inplace=False):
        super(TemporalShift, self).__init__()
        # self.net = net
        self.n_segment = n_segment
        self.fold_div = n_div
        self.inplace = inplace
        self.channels_range = list(range(2048))  # feature_channels
        if inplace:
            print('=> Using in-place shift...')
        # print('=> Using fold div: {}'.format(self.fold_div))

    def forward(self, x):
        # self.fold_div = n_div
        x = self.shift(x, self.n_segment, fold_div=self.fold_div, inplace=self.inplace, channels_range =self.channels_range)
        return x

    @staticmethod
    def shift(x, n_segment, fold_div=8, inplace=False, channels_range=[1,2]):
        x = x.permute(0, 2, 1)   # [B,C,T] --> [B, T, C]
        # set_trace()
        n_batch, T, c = x.size()
        # nt, c, h, w = x.size()
        # n_batch = nt // n_segment
        # x = x.view(n_batch, n_segment, c, h, w)
        # x = x.view(n_batch, T, c, h, w)
        fold = c // 2*fold_div
        # all = random.sample(channels_range, fold*2)
        # forward = sorted(all[:fold])
        # backward = sorted(all[fold:])
        # fixed = list(set(channels_range) - set(all))
        # fold = c // fold_div

        if inplace:
            # Due to some out of order error when performing parallel computing.
            # May need to write a CUDA kernel.
            raise NotImplementedError
            # out = InplaceShift.apply(x, fold)
        else:
            out = torch.zeros_like(x)
            out[:, :-1, :fold] = x[:, 1:, :fold]  # shift left
            out[:, 1:, fold: 2 * fold] = x[:, :-1, fold: 2 * fold]  # shift right
            out[:, :, 2 * fold:1024] = x[:, :, 2 * fold:1024]  # not shift

            out[:, :-1, 1024:1024+fold] = x[:, 1:, 1024:1024+fold]  # shift left
            out[:, 1:, 1024+fold: 1024+2 * fold] = x[:, :-1, 1024+fold: 1024+2 * fold]  # shift right
            out[:, :, 1024+2 * fold:] = x[:, :, 1024 + 2 * fold:]  # not shift
            # out = torch.zeros_like(x)
            # out[:, :-1, forward] = x[:, 1:, forward]  # shift left
            # out[:, 1:, backward] = x[:, :-1, backward]  # shift right
            # out[:, :, fixed] = x[:, :, fixed]  # not shift

        # return out.view(nt, c, h, w)
        return out.permute(0, 2, 1)


class TemporalShift_random(nn.Module):
    def __init__(self, n_segment=3, n_div=8, inplace=False):
        super(TemporalShift_random, self).__init__()
        # self.net = net
        self.n_segment = n_segment
        self.fold_div = n_div
        self.inplace = inplace
        self.channels_range = list(range(2048))  # feature_channels
        if inplace:
            print('=> Using in-place shift...')
        # print('=> Using fold div: {}'.format(self.fold_div))

    def forward(self, x):
        # self.fold_div = n_div
        x = self.shift(x, self.n_segment, fold_div=self.fold_div, inplace=self.inplace, channels_range =self.channels_range)
        return x

    @staticmethod
    def shift(x, n_segment, fold_div=8, inplace=False, channels_range=[1,2]):
        x = x.permute(0, 2, 1)   # [B,C,T] --> [B, T, C]
        # set_trace()
        n_batch, T, c = x.size()
        # nt, c, h, w = x.size()
        # n_batch = nt // n_segment
        # x = x.view(n_batch, n_segment, c, h, w)
        # x = x.view(n_batch, T, c, h, w)
        fold = c // fold_div
        all = random.sample(channels_range, fold*2)
        forward = sorted(all[:fold])
        backward = sorted(all[fold:])
        fixed = list(set(channels_range) - set(all))
        # fold = c // fold_div

        if inplace:
            # Due to some out of order error when performing parallel computing.
            # May need to write a CUDA kernel.
            raise NotImplementedError
            # out = InplaceShift.apply(x, fold)
        else:
            # out = torch.zeros_like(x)
            # out[:, :-1, :fold] = x[:, 1:, :fold]  # shift left
            # out[:, 1:, fold: 2 * fold] = x[:, :-1, fold: 2 * fold]  # shift right
            # out[:, :, 2 * fold:] = x[:, :, 2 * fold:]  # not shift
            out = torch.zeros_like(x)
            out[:, :-1, forward] = x[:, 1:, forward]  # shift left
            out[:, 1:, backward] = x[:, :-1, backward]  # shift right
            out[:, :, fixed] = x[:, :, fixed]  # not shift

        # return out.view(nt, c, h, w)
        return out.permute(0, 2, 1)


class InplaceShift(torch.autograd.Function):
    # Special thanks to @raoyongming for the help to this function
    @staticmethod
    def forward(ctx, input, fold):
        # not support higher order gradient
        # input = input.detach_()
        ctx.fold_ = fold
        n, t, c, h, w = input.size()
        buffer = input.data.new(n, t, fold, h, w).zero_()
        buffer[:, :-1] = input.data[:, 1:, :fold]
        input.data[:, :, :fold] = buffer
        buffer.zero_()
        buffer[:, 1:] = input.data[:, :-1, fold: 2 * fold]
        input.data[:, :, fold: 2 * fold] = buffer
        return input

    @staticmethod
    def backward(ctx, grad_output):
        # grad_output = grad_output.detach_()
        fold = ctx.fold_
        n, t, c, h, w = grad_output.size()
        buffer = grad_output.data.new(n, t, fold, h, w).zero_()
        buffer[:, 1:] = grad_output.data[:, :-1, :fold]
        grad_output.data[:, :, :fold] = buffer
        buffer.zero_()
        buffer[:, :-1] = grad_output.data[:, 1:, fold: 2 * fold]
        grad_output.data[:, :, fold: 2 * fold] = buffer
        return grad_output, None

class BMN(nn.Module):
    def __init__(self, opt):
        super(BMN, self).__init__()
        self.feat_dim=opt["feat_dim"]                              # 400
        self.n_heads = 4
        self.num_classes = 26
        self.hidden_dim_1d = 256
        self.tem_best_loss = 10000000
        # Base Module
        self.x_1d_b = nn.Sequential(
            nn.Conv1d(self.feat_dim, self.hidden_dim_1d, kernel_size=3, padding=1, groups=4), 
            # nn.BatchNorm1d(self.hidden_dim_1d),     
            nn.ReLU(inplace=True),
            nn.Conv1d(self.hidden_dim_1d, self.hidden_dim_1d, kernel_size=3, padding=1, groups=4),  # 256
            # nn.BatchNorm1d(self.hidden_dim_1d),
            nn.ReLU(inplace=True)
        )
        self.recons = nn.Sequential(
            nn.Conv1d(self.hidden_dim_1d, self.hidden_dim_1d, kernel_size=3, padding=1, groups=4),
            # nn.BatchNorm1d(self.hidden_dim_1d),
            nn.ReLU(inplace=True),
            nn.Conv1d(self.hidden_dim_1d, self.feat_dim, kernel_size=3, padding=1, groups=4)  # 256
            # nn.ReLU(inplace=True)
        )
        self.clip_order_linear = nn.Linear(100, 2)
        self.clip_order_drop = nn.Dropout(0.5)
        self.clip_order = nn.Sequential(
            nn.Conv1d(self.hidden_dim_1d, 1, kernel_size=3, padding=1),  # 256
            nn.ReLU(inplace=True)
        )
        # Classification
        self.embedding = SnippetEmbedding(self.n_heads, self.feat_dim,self.feat_dim,self.feat_dim,0.3)
        self.classifier = nn.Sequential(nn.Conv1d(self.feat_dim, self.num_classes, kernel_size=1,padding=0))
        self.SingleStageTCN = SingleStageTCN(2048, 16, 25, 0)
        self.SingleStageTCN_new = SingleStageTCN_new(2048, 16, 25, 0)
        self.SingleStageTCN_new1 = SingleStageTCN_new1(2048,0)
        self.fc_new1 = nn.Sequential(nn.Linear(8,1))
        self.fc = nn.Sequential(nn.Linear(4,1))
    def forward(self, x, recons=False, clip_order=False):                   # [B,400,100]
        base_feature = self.x_1d_b(x)                # [B,256,100]
        recons_feature = self.recons(base_feature)
        batch_size, C, T = base_feature.size()
        if recons:
            return recons_feature
        if clip_order:
            return self.clip_order_linear(self.clip_order_drop(self.clip_order(base_feature).view(batch_size, T)))        
        ### classification
        snip = x.permute(0,2,1)
        out = self.embedding(snip, snip, snip)
        out = out.permute(0,2,1)
        out = out + x
        #out = self.SingleStageTCN(out)
        out = self.SingleStageTCN_new(out)
        top_br = self.fc(out.mean(dim=2))
        # out = self.SingleStageTCN_new1(out)
        # top_br = self.fc_new1(out.mean(dim=2))
        return out, top_br      # [B, 2, 100, 100], [B,100],[B,100]

    def _boundary_matching_layer(self, x):
        input_size = x.size()    # [B,256,100]
        out = torch.matmul(x, self.sample_mask).reshape(input_size[0],input_size[1],self.num_sample,self.tscale,self.tscale)
        return out           # sample_mask= [100, 320000]

    def _get_interp1d_bin_mask(self, seg_xmin, seg_xmax, tscale, num_sample, num_sample_perbin):
        # generate sample mask for a boundary-matching pair
        plen = float(seg_xmax - seg_xmin)      # during
        plen_sample = plen / (num_sample * num_sample_perbin - 1.0)    
        total_samples = [
            seg_xmin + plen_sample * ii
            for ii in range(num_sample * num_sample_perbin)
        ]                           # num_sample * num_sample_perbin 
        p_mask = []
        for idx in range(num_sample):             # 32
            bin_samples = total_samples[idx * num_sample_perbin:(idx + 1) * num_sample_perbin]
            bin_vector = np.zeros([tscale])
            for sample in bin_samples:
                sample_upper = math.ceil(sample)
                sample_decimal, sample_down = math.modf(sample)   
                if int(sample_down) <= (tscale - 1) and int(sample_down) >= 0:  
                    bin_vector[int(sample_down)] += 1 - sample_decimal          # down
                if int(sample_upper) <= (tscale - 1) and int(sample_upper) >= 0:
                    bin_vector[int(sample_upper)] += sample_decimal            # upper
            bin_vector = 1.0 / num_sample_perbin * bin_vector         
            p_mask.append(bin_vector)
        p_mask = np.stack(p_mask, axis=1)         # 100*32  
        return p_mask

    def _get_interp1d_mask(self):
        # generate sample mask for each point in Boundary-Matching Map
        mask_mat = []
        for start_index in range(self.tscale):           # 100
            mask_mat_vector = []
            for duration_index in range(self.tscale):    # 100
                if start_index + duration_index < self.tscale:   # 
                    p_xmin = start_index                      # start
                    p_xmax = start_index + duration_index     # end
                    center_len = float(p_xmax - p_xmin) + 1    # during
                    sample_xmin = p_xmin - center_len * self.prop_boundary_ratio   # sample_start
                    sample_xmax = p_xmax + center_len * self.prop_boundary_ratio   # sample_end
                    p_mask = self._get_interp1d_bin_mask(
                        sample_xmin, sample_xmax, self.tscale, self.num_sample,     # 32
                        self.num_sample_perbin)
                else:
                    p_mask = np.zeros([self.tscale, self.num_sample])    # [100,32]
                mask_mat_vector.append(p_mask)                        # 
            mask_mat_vector = np.stack(mask_mat_vector, axis=2)            # [100,32,100]
            mask_mat.append(mask_mat_vector)
        mask_mat = np.stack(mask_mat, axis=3)                     # [100,32,100,100]
        mask_mat = mask_mat.astype(np.float32)
        self.sample_mask = nn.Parameter(torch.Tensor(mask_mat).view(self.tscale, -1), requires_grad=False)  # [100,32*100*100]



if __name__ == '__main__':
    import opts
    opt = opts.parse_opt()
    opt = vars(opt)
    model=BMN(opt).cuda()
    input=torch.randn(2,2048,100).cuda()
    a,b,c=model(x=input)
    print(a.shape,b.shape,c.shape)
