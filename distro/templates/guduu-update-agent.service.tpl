[Unit]
Description=GuDuu OS OEM version update agent
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory={{DISTRO_DIR}}
ExecStartPre=/usr/bin/install -d -m 0770 {{DISTRO_DIR}}/data/cosmac
ExecStart=/usr/bin/python3 {{DISTRO_DIR}}/update_agent.py
User=root
Group=root
UMask=0007
NoNewPrivileges=true
PrivateTmp=true
