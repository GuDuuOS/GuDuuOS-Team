# ============================================================
# CosMac 发行版 —— Caddy 配置模板（共存模式：躲在宿主反向代理后面）
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
}

:80 {
	encode zstd gzip

	# —— Matrix 协议层（🚫 路径一个字都不能改，见 CLAUDE.md §7）——
	@matrix path /_matrix/* /_synapse/client/*
	handle @matrix {
		reverse_proxy synapse:8008
	}

	# —— CosMac 自有 API ——
	handle /cosmac/* {
		reverse_proxy bot:9000
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
