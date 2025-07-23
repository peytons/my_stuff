#!/bin/bash
branches=$(git for-each-ref --format="%(committerdate:short) %(refname:short)" --sort=committerdate refs/heads/ | awk '$1 < "2024-10-01" {print $2}')
for branch in $branches; do
  if [ "$branch" != "main" ] && [ "$branch" != "master" ]; then
    echo -e "\nBranch: $branch"
    git log -1 --pretty=format:"%h - %an, %ar : %s" $branch
    echo ""
    read -p "Delete this branch? (y/n/q to quit): " confirm
    if [ "$confirm" = "q" ]; then
      echo "Quitting..."
      exit 0
    elif [ "$confirm" = "y" ]; then
      git branch -d $branch
      if [ $? -ne 0 ]; then
        echo "Branch is not fully merged. Use force delete? (y/n): "
        read force
        if [ "$force" = "y" ]; then
          git branch -D $branch
          echo "Force deleted branch: $branch"
        fi
      else
        echo "Deleted branch: $branch"
      fi
    else
      echo "Skipping branch: $branch"
    fi
  fi
done
