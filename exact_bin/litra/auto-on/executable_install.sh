#!/usr/bin/env zsh

source ${HOME}/bin/_common.zsh

script_dir=${0:A:h}
script_name=$(basename $0)

setup_cmd() {
    src=$1
    src_base=$(basename $src)
    dst=/Library/LaunchDaemons/$src_base
    if [[ "$script_name" == "install.sh" ]]; then
        _exec sudo cp $src $dst
        if [[ "$src_base" != "hidapitester" ]]; then
            _exec sudo chmod 0744 $dst
            _exec sudo chown root:wheel $dst
        fi
    elif [[ "$script_name" == "uninstall.sh" ]]; then
        _exec sudo rm -rf $dst
    fi
}

for file in ${script_dir}/{litra-auto-on.plist,litra-auto-on.sh} ${HOME}/bin/hidapitester ; do
    setup_cmd $file
done

if [[ "$script_name" == "install.sh" ]]; then 
    echo "Use below to start:"
    echo "sudo launchctl bootstrap system /Library/LaunchDaemons/litra-auto-on.plist"
fi