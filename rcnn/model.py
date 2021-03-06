import torch
import torch.nn as nn

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")


class RCNN(nn.Module):

    def __init__(self, cfg, verbose=False):
        super(RCNN, self).__init__()
        self.cfg = cfg
        self.verbose = verbose

        self.activation = torch.nn.ReLU
        self.bn_con = nn.BatchNorm1d(len(cfg['con']), momentum=None)

        n_cat_static = len(cfg['cat_static'])
        self.static_embd = nn.ModuleList(
            [nn.Embedding(x, y) for x, y in zip(cfg['n_class'][:n_cat_static], cfg['embd_size'][:n_cat_static])]
        )
        self.seq_embd = nn.ModuleList(
            [nn.Embedding(x, y) for x, y in zip(cfg['n_class'][n_cat_static:], cfg['embd_size'][n_cat_static:])]
        )

        self.lstm_encoder = nn.LSTM(
            input_size=sum(cfg['embd_size'][n_cat_static:]) + len(cfg['con']),
            hidden_size=cfg['hidden'],
            num_layers=cfg['layer'], batch_first=True
        )
        self.lstm_decoder = nn.LSTMCell(
            input_size=sum(cfg['embd_size'][n_cat_static:]) + len(cfg['con']),
            hidden_size=cfg['hidden']
        )

        self.fc = nn.Sequential(
            nn.Linear(cfg['hidden'] + sum(cfg['embd_size'][:n_cat_static]), 128), self.activation(),
            nn.Linear(128, 64), self.activation(),
            nn.Linear(64, 32), self.activation(),
            nn.Linear(32, 1), self.activation()
        )
        self.to(device)

    def forward(self, x, x_seq):
        self.lstm_encoder.flatten_parameters()
        bs = x.size(0)
        n_cat_seq = len(self.cfg['cat_seq'])
        in_steps = self.cfg['in_steps']

        x = x.long().to(device)
        x_seq_cat = x_seq[:, :, :n_cat_seq].long().to(device)
        x_seq_con = x_seq[:, :, n_cat_seq:].float().to(device)
        if self.verbose: print('x:         ', x.size())
        if self.verbose: print('x_seq_cat: ', x_seq_cat.size())
        if self.verbose: print('x_seq_con: ', x_seq_con.size())

        x = [embd(x[:, i]) for i, embd in enumerate(self.static_embd)]
        x = torch.cat(x, dim=1)
        if self.verbose: print('x:         ', x.size())

        x_seq_cat = [embd(x_seq_cat[:, :, i]) for i, embd in enumerate(self.seq_embd)]
        x_seq_cat = torch.cat(x_seq_cat, 2)
        if self.cfg['batch_normalization']:
            x_seq_con = self.bn_con(x_seq_con)
        x_seq = torch.cat([x_seq_cat, x_seq_con], dim=2)
        if self.verbose: print('x_seq:     ', x_seq.size())

        encoder_in = x_seq[:, :in_steps, :]
        encoder_out, (hn, cn) = self.lstm_encoder(encoder_in)
        hn = hn[-1, :, :].view(bs, self.cfg['hidden'])
        cn = cn[-1, :, :].view(bs, self.cfg['hidden'])

        outputs = []
        decoder_in = x_seq[:, in_steps:, :-1].clone().detach()
        for i in range(self.cfg['out_steps']):
            if i == 0:
                step_decoder_in = torch.cat([decoder_in[:, i, :], encoder_in[:, -1, -1:]], dim=1)
            else:
                step_decoder_in = torch.cat([decoder_in[:, i, :], out], dim=1)
            (hn, cn) = self.lstm_decoder(step_decoder_in, (hn, cn))
            out = torch.cat([x, hn], dim=1)
            out = self.fc(out)
            outputs.append(out)

        out = torch.cat(outputs, dim=1).view(bs, -1, 1)
        return out
