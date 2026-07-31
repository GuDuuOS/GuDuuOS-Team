[Unit]
Description=Check GuDuu Nexus for OEM version updates

[Timer]
OnBootSec=2min
OnUnitActiveSec=5min
RandomizedDelaySec=45s
Persistent=true
Unit=guduu-update-agent.service

[Install]
WantedBy=timers.target
