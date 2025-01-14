import torch
import torch.nn as nn
import numpy as np
import torch.nn.functional as F
from ipdb import set_trace

class FixedPositionalEncoding(nn.Module):
    def __init__(self, embedding_dim, max_length=5000):
        super(FixedPositionalEncoding, self).__init__()
        
        pe = torch.zeros(max_length, embedding_dim)
        position = torch.arange(0, max_length, dtype=torch.float).unsqueeze(1)
        div_term = torch.exp(
            torch.arange(0, embedding_dim, 2).float()
            * (-torch.log(torch.tensor(10000.0)) / embedding_dim)
        )
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        pe = pe.unsqueeze(0).transpose(0, 1)
        self.register_buffer('pe', pe.squeeze(1))
        

    def forward(self, x):
        # print(x.size())
        x = x + self.pe[: x.size(0), :]
        return x

class LearnedPositionalEncoding(nn.Module):
    def __init__(self, max_position_embeddings, embedding_dim, seq_length):
        super(LearnedPositionalEncoding, self).__init__()
        self.pe = nn.Embedding(max_position_embeddings, embedding_dim)
        self.seq_length = seq_length

        self.register_buffer(
            "position_ids",
            torch.arange(max_position_embeddings).expand((1, -1)),
        )

    def forward(self, x, position_ids=None):
        if position_ids is None:
            position_ids = self.position_ids[:, : self.seq_length]

        position_embeddings = self.pe(position_ids)
        return x + position_embeddings


class ScaledDotProductAttention(nn.Module):
    ''' Scaled Dot-Product Attention '''

    def __init__(self, temperature, attn_dropout=0.1):
        super().__init__()
        self.temperature = temperature
        self.dropout = nn.Dropout(attn_dropout)
        self.softmax = nn.Softmax(dim=2)

    def forward(self, q, k, v):

        attn = torch.bmm(q, k.transpose(1, 2))
        attn = attn / self.temperature
        log_attn = F.log_softmax(attn, 2)
        attn = self.softmax(attn)
        attn = self.dropout(attn)
        output = torch.bmm(attn, v)
        # print("v", v)
        return output, attn, log_attn

class SnippetEmbedding(nn.Module):


    def __init__(self, n_head, d_model, d_k, d_v, dropout, clip_order=False):
        super().__init__()
        self.n_head = n_head # 1
        self.d_k = d_k # 256
        self.d_v = d_v # 256 , d_model : 256
        self.pos_enc = LearnedPositionalEncoding(2048,2048,100)
        self.clip_order = clip_order
        self.w_qs = nn.Linear(d_model, n_head * d_k, bias=False).cuda()
        self.w_qs.requires_grad = True
        self.w_ks = nn.Linear(d_model, n_head * d_k, bias=False).cuda()
        self.w_vs = nn.Linear(d_model, n_head * d_v, bias=False).cuda()
        nn.init.normal_(self.w_qs.weight, mean=0, std=np.sqrt(2.0 / (d_model + d_k)))
        nn.init.normal_(self.w_ks.weight, mean=0, std=np.sqrt(2.0 / (d_model + d_k)))
        nn.init.normal_(self.w_vs.weight, mean=0, std=np.sqrt(2.0 / (d_model + d_v)))

        self.attention = ScaledDotProductAttention(temperature=np.power(d_k, 0.5))
        self.layer_norm = nn.LayerNorm(d_model).cuda()
        self.fc = nn.Linear(n_head * d_v, d_model).cuda()
        nn.init.xavier_normal_(self.fc.weight)
        self.dropout = nn.Dropout(dropout)
        
    def forward(self, q, k, v):
        d_k, d_v, n_head = self.d_k, self.d_v, self.n_head
        sz_b, len_q, _ = q.size()
        sz_b, len_k, _ = k.size()
        sz_b, len_v, _ = v.size()
        # print(q.size())
        if self.clip_order:
            q = self.pos_enc(q)
            k = self.pos_enc(k)
            v = self.pos_enc(v)
        residual = q
        q = self.w_qs(q).view(sz_b, len_q, n_head, d_k)
        k = self.w_ks(k).view(sz_b, len_k, n_head, d_k)
        v = self.w_vs(v).view(sz_b, len_v, n_head, d_v)

        q = q.permute(2, 0, 1, 3).contiguous().view(-1, len_q, d_k) # (n*b) x lq x dk
        k = k.permute(2, 0, 1, 3).contiguous().view(-1, len_k, d_k) # (n*b) x lk x dk
        v = v.permute(2, 0, 1, 3).contiguous().view(-1, len_v, d_v) # (n*b) x lv x dv

        output, attn, log_attn = self.attention(q, k, v)
        output = output.view(n_head, sz_b, len_q, d_v)
        output = output.permute(1, 2, 0, 3).contiguous().view(sz_b, len_q, -1) # b x lq x (n*dv)
        
        output = self.dropout(self.fc(output))
        output = self.layer_norm(output + residual)
        return output
    
class SingleStageTCN(nn.Module):
    def __init__(self, num_feature, embed_dim, temp_window, dropout):
        super(SingleStageTCN, self).__init__()
        self.convL1 = nn.Conv1d(num_feature,64,temp_window,padding='same')
        self.convL2 = nn.Conv1d(64,32,temp_window,padding='same')
        self.convL3 = nn.Conv1d(32,16,temp_window,padding='same')
        self.convL4 = nn.Conv1d(16,16,temp_window,padding='same')
        #self.convL5 = nn.Conv1d(16,embed_dim,temp_window,padding='same')
        self.dropout = nn.Dropout(dropout)
        self.pool = nn.MaxPool1d(3,3)
        self.bn1 = nn.BatchNorm1d(64)
        self.bn2 = nn.BatchNorm1d(32)
        self.bn3 = nn.BatchNorm1d(16)
        self.bn4 = nn.BatchNorm1d(16)
        #self.bn5 = nn.BatchNorm1d(embed_dim)
    def forward(self, x):
        x = self.dropout(self.bn1(self.pool(F.relu(self.convL1(x)))))
        #set_trace()
        x = self.dropout(self.bn2(self.pool(F.relu(self.convL2(x)))))
        x = self.dropout(self.bn3(self.pool(F.relu(self.convL3(x)))))
        x = self.dropout(self.bn4(self.pool(F.relu(self.convL4(x)))))
        #x = self.dropout(self.bn5(self.pool(F.relu(self.convL5(x)))))
        return x

class SingleStageTCN_new(nn.Module):
    def __init__(self, num_feature, embed_dim, temp_window, dropout):
        super(SingleStageTCN_new, self).__init__()
        self.convL1 = nn.Conv1d(num_feature,256,temp_window,padding='same')
        self.convL2 = nn.Conv1d(256,64,temp_window,padding='same')
        self.convL3 = nn.Conv1d(64,16,temp_window,padding='same')
        self.convL4 = nn.Conv1d(16,4,temp_window,padding='same')
        #self.convL5 = nn.Conv1d(16,embed_dim,temp_window,padding='same')
        self.dropout = nn.Dropout(dropout)
        self.pool = nn.MaxPool1d(3,3)
        self.bn1 = nn.BatchNorm1d(256)
        self.bn2 = nn.BatchNorm1d(64)
        self.bn3 = nn.BatchNorm1d(16)
        self.bn4 = nn.BatchNorm1d(4)
        #self.bn5 = nn.BatchNorm1d(embed_dim)
    def forward(self, x):
        x = self.dropout(self.bn1(self.pool(F.relu(self.convL1(x)))))
        #set_trace()
        x = self.dropout(self.bn2(self.pool(F.relu(self.convL2(x)))))
        x = self.dropout(self.bn3(self.pool(F.relu(self.convL3(x)))))
        x = self.dropout(self.bn4(self.pool(F.relu(self.convL4(x)))))
        #x = self.dropout(self.bn5(self.pool(F.relu(self.convL5(x)))))
        return x

class SingleStageTCN_new1(nn.Module):
    def __init__(self, num_feature, dropout):
        super(SingleStageTCN_new1, self).__init__()
        self.convL1 = nn.Conv1d(num_feature,512,16,padding='same')
        self.convL2 = nn.Conv1d(512,128,16,padding='same')
        self.convL3 = nn.Conv1d(128,32,16,padding='same')
        self.convL4 = nn.Conv1d(32,8,16,padding='same')
        self.convL5 = nn.Conv1d(8,8,16,padding='same')
        self.dropout = nn.Dropout(dropout)
        self.pool = nn.MaxPool1d(3,3)
        self.bn1 = nn.BatchNorm1d(512)
        self.bn2 = nn.BatchNorm1d(128)
        self.bn3 = nn.BatchNorm1d(32)
        self.bn4 = nn.BatchNorm1d(8)
        self.bn5 = nn.BatchNorm1d(8)
    def forward(self, x):
        x = self.dropout(self.bn1(self.pool(F.relu(self.convL1(x)))))
        #set_trace()
        x = self.dropout(self.bn2(self.pool(F.relu(self.convL2(x)))))
        x = self.dropout(self.bn3(self.pool(F.relu(self.convL3(x)))))
        x = self.dropout(self.bn4(self.pool(F.relu(self.convL4(x)))))
        x = self.dropout(self.bn5(self.pool(F.relu(self.convL5(x)))))
        return x
