source ~/bin/git_svn_bash_prompt.sh
source ~/.aliases
export PATH="~/Dropbox/My Documents/Projects/pebble/PebbleSDK-2.0-BETA6/bin:$PATH"
[ -d /Applications/Visual\ Studio\ Code.app/Contents/Resources/app/bin ] && export PATH="$PATH:/Applications/Visual Studio Code.app/Contents/Resources/app/bin"

# added by travis gem
[ -f /Users/peyton/.travis/travis.sh ] && source /Users/peyton/.travis/travis.sh

[ -f /opt/homebrew/bin/brew ] && eval "$(/opt/homebrew/bin/brew shellenv)"

[ -f /opt/homebrew/etc/bash_completion.d/git-completion.bash ] && source /opt/homebrew/etc/bash_completion.d/git-completion.bash

# pnpm
export PNPM_HOME="/Users/peyton/Library/pnpm"
case ":$PATH:" in
  *":$PNPM_HOME:"*) ;;
  *) export PATH="$PNPM_HOME:$PATH" ;;
esac
# pnpm end
#
# React editor
export REACT_EDITOR=cursor
# end
#
#
