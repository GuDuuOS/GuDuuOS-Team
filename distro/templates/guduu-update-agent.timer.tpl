[Unit]
Description=Check GuDuu Nexus for OEM version updates

[Timer]
OnActiveSec=30s
OnUnitActiveSec=5min
RandomizedDelaySec=45s
Persistent=true
Unit=guduu-update-agent.service

[Install]
WantedBy=timers.target
