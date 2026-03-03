#!/bin/bash

input=$(cat)
cwd=$(echo "$input" | jq -r '.cwd')
project=$(basename "$cwd")
notification_type=$(echo "$input" | jq -r '.notification_type')

case "$notification_type" in
  "permission_prompt")
    terminal-notifier -title "Claude Code" -subtitle "$project" -message "許可待ち" -sound "Ping"
    ;;
  "idle_prompt")
    terminal-notifier -title "Claude Code" -subtitle "$project" -message "入力待ち" -sound "Purr"
    ;;
  "stop")
    terminal-notifier -title "Claude Code" -subtitle "$project" -message "タスク完了" -sound "Glass"
    ;;
  *)
    terminal-notifier -title "Claude Code" -subtitle "$project" -message "通知" -sound ""
    ;;
esac
