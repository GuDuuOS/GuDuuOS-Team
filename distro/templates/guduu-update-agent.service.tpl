[Unit]
Description=GuDuu OS OEM version update agent
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory={{DISTRO_DIR}}
ExecStart=/usr/bin/python3 {{DISTRO_DIR}}/update_agent.py
User=root
Group=root
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
