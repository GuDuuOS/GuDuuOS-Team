# ============================================================
# GuDuu OS 发行版 —— Caddy 配置模板（共存模式：躲在宿主反向代理后面）
# ------------------------------------------------------------
# 与 Caddyfile.tpl 的区别：本模式下 TLS 由**宿主机的**反代（Caddy/nginx）
# 终结，容器里的 Caddy 只在 :80 提供明文 HTTP，不签证书、不占宿主 443。
# 适用场景：一台服务器同时跑多套服务（如国内生产机：star 主站 + nexus 母舰），
# 宿主反代按域名分发到各自的本地端口。
# install.sh --behind-proxy 时选用本模板。
# ============================================================

# 全局：关掉自动 HTTPS（证书是宿主反代的事）
{
	auto_https off
	# 信任私网内的上游反代(宿主 Caddy/nginx):据其 X-Forwarded-For 还原**真实客户端 IP**。
	# 否则双层反代下容器只看到网关 172.18.0.1,登录限频把全平台当同一 IP 一起限流→误报
	# "尝试过于频繁"、正常用户登不上(负责人实报)。private_ranges 只信私网跳,公网直连不受影响。
	servers {
		trusted_proxies static private_ranges
	}
}

:80 {
	encode zstd gzip

	# —— Matrix 协议层（🚫 路径一个字都不能改，见 CLAUDE.md §7）——
	@matrix path /_matrix/* /_synapse/client/* /_synapse/admin/*
	handle @matrix {
		reverse_proxy synapse:8008
	}

	# —— GuDuu OS 自有 API ——
	# 把还原出的真实客户端 IP 用 X-Real-IP 传给 bot(bot 优先认它):登录限频/异地检测/审计
	# 才拿得到真实 IP。client_ip 已由上面的 trusted_proxies 从 XFF 正确还原。
	handle /cosmac/* {
		reverse_proxy bot:9000 {
			header_up X-Real-IP {http.request.client_ip}
		}
	}

	# —— 联邦/客户端服务发现（域名在渲染时固定写入）——
	handle /.well-known/matrix/server {
		header Content-Type application/json
		respond `{"m.server": "{{DOMAIN}}:443"}` 200
	}
	handle /.well-known/matrix/client {
		header Content-Type application/json
		header Access-Control-Allow-Origin *
		respond `{"m.homeserver": {"base_url": "https://{{DOMAIN}}"}}` 200
	}

	# —— 前端静态 ——
	handle {
		root * /srv
		try_files {path} /index.html
		file_server
	}
}
