set makeprg=texwrapper\ -rc2l\ --format\ pdflatex\ '%'
set errorformat=%f:%l:%c:%m
set autoread
noh

map <S-F4> :silent !~/bin/porzadki.pl %<CR>
map <F5> :silent !open '%<.pdf'<CR>
map <F6> <F4><F5>

set foldmethod=marker
set foldmarker=(fold),(end)
