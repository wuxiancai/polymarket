#!/bin/bash
# 检查 Chrome 是否已在运行
if ! pgrep "Google Chrome" > /dev/null; then
    /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222 &
    echo "Chrome 已启动，调试端口: 9222"
else
    echo "Chrome 已在运行"
fi
