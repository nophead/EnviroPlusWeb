#!/bin/bash
SERVICE_PATH=/etc/systemd/system/enviroplus_web.service

read -r -d '' UNIT_FILE << EOF
[Unit]
Description=Enviro+ web service
After=multi-user.target

[Service]
Type=simple
WorkingDirectory=$(pwd)
ExecStart=sudo python3 $(pwd)/app.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF



printf "\nInstalling service to: $SERVICE_PATH\n"
echo "$UNIT_FILE" > $SERVICE_PATH
systemctl daemon-reload
systemctl enable --no-pager enviroplus_web.service
systemctl restart --no-pager enviroplus_web.service
systemctl status --no-pager enviroplus_web.service
