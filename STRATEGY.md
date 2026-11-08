# Strategy

The score is a sum of logs, so the cost of being wrong is asymmetric: a place
where the right game got nothing costs -9.21, and no amount of confidence
elsewhere buys it back. That makes this a calibration problem, not a ranking
problem. A forecast that nails nine places and misses the tenth scores worse
than one that spreads a little everywhere.

Three decisions follow from it. First, the diffusion coefficient is estimated
from the history rather than fixed, because the chart's own archive shows a
median of five places changing between reads a few hours apart: the walk is
wide, and a narrow kernel would lose the log score at the places that move.
Second, the forecast is averaged over the window's hours, since the same file
is read at every hour and the median hour is not the first one. Third, each
place keeps 10 percent unnamed, so a game the history has never seen is not a
near-zero event: the house baseline, which bets on no movement, loses the whole
mass of any arrival.

The rejected alternative was a transition matrix over observed place pairs.
With 26 reads the matrix is mostly empty, so it would encode the few moves that
happened rather than the width of the walk, and it would give zero to any move
the archive never made.
