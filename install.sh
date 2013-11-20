#!/bin/bash
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
echo Installing from $DIR
ln -s $DIR/.gitconfig ~/.gitconfig
ln -s $DIR/.bash_profile ~/.bash_profile
ln -s $DIR/.bashrc ~/.bashrc
ln -s $DIR/bin ~/bin
ln -s $DIR/.aliases ~/.aliases
