#!/bin/bash

# جاهایی که اسم اکانت هست رو باید با اسم اکانت خودتون عوض  کنید
PID_FILE="/usr/home/account/set_bot.pid"
LOG_FILE="/usr/home/account/bot.log"


echo "$(date) - Checking bot process status" >> "$LOG_FILE"


if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if [ -n "$OLD_PID" ] && ps -p "$OLD_PID" > /dev/null; then
        echo "$(date) - Bot already running with PID $OLD_PID" >> "$LOG_FILE"
        exit 0
    else
        echo "$(date) - No active process found for PID $OLD_PID, cleaning up" >> "$LOG_FILE"
        rm -f "$PID_FILE"
    fi
fi


if ps aux | grep -q "[p]ython3.*set\.py"; then
    CURRENT_PID=$(ps aux | grep "[p]ython3.*set\.py" | awk '{print $2}' | head -n 1)
    echo "$(date) - Unexpected bot process found with PID $CURRENT_PID, stopping it" >> "$LOG_FILE"
    kill -9 "$CURRENT_PID" 2>/dev/null
    sleep 2
fi

# اینجا نیاز به ادیت داره اسم اکانت خودتونو وارد کنید
echo "$(date) - Starting new bot session" >> "$LOG_FILE"
cd /usr/home/account || { echo "$(date) - Failed to cd to /usr/home/account" >> "$LOG_FILE"; exit 1; }
/usr/local/bin/python3 /usr/home/account/set.py >> "$LOG_FILE" 2>&1 &
NEW_PID=$!
sleep 1  


if ps -p "$NEW_PID" > /dev/null; then
    echo "$NEW_PID" > "$PID_FILE"
    echo "$(date) - Started new bot session with PID $NEW_PID" >> "$LOG_FILE"
else
    echo "$(date) - Failed to start new bot session, PID $NEW_PID not found" >> "$LOG_FILE"
fi
