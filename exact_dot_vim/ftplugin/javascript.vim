let g:jsx_ext_required = 0

let g:formatprg_args_expr_javascript = '"-f - -p -m2 --good-stuff -i -s".&shiftwidth'
au BufEnter call JavaScriptFold()

let g:javascript_conceal_function   = "ƒ"
let g:javascript_conceal_null       = "ø"
let g:javascript_conceal_this       = "@"
let g:javascript_conceal_return     = "⇚"
let g:javascript_conceal_undefined  = "¿"
let g:javascript_conceal_NaN        = "ℕ"
let g:javascript_conceal_prototype  = "¶"
let g:javascript_conceal_static     = "•"
let g:javascript_conceal_super      = "Ω"

let g:used_javascript_libs = 'jquery,angularjs,angularui'
let g:UltiSnipsSnippetDirectories += ['$HOME/.vim/bundle/angular-vim-snippets/UltiSnips']

