let g:ruby_debugger_progname = 'mvim'

set foldlevel=3

nmap [[ ?def <CR>
nmap ]] /def <CR>

set cinoptions=:0,p0,t0
set cinwords=if,else,while,do,for,switch,case
set expandtab

set tags+=gems.tags

nmap K :Dash<cr>

nmap <s-f2> :A<cr>
nmap <s-f3> :R<cr>

nmap <buffer> <F5> <Plug>(xmpfilter-run)
xmap <buffer> <F5> <Plug>(xmpfilter-run)
imap <buffer> <F5> <Plug>(xmpfilter-run)

nmap <buffer> <S-F5> <Plug>(xmpfilter-mark)
xmap <buffer> <S-F5> <Plug>(xmpfilter-mark)
imap <buffer> <S-F5> <Plug>(xmpfilter-mark)

nmap <buffer> <F3> :!rubocop -a % 2> /dev/null<cr>

au BufEnter Podfile map <f3> :!pod update<cr>

let g:neocomplete#disable_auto_complete = 1
