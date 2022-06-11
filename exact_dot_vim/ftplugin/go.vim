let g:acp_enableAtStartup = 1
let g:neocomplete#enable_at_startup = 1

au FileType go nmap <f5> <Plug>(go-run)
au FileType go nmap <f4> <Plug>(go-lint)
