# ============================================================
# GuDuu OS 发行版 —— Caddy 配置模板（install.sh 渲染到 data/caddy/Caddyfile）
# ------------------------------------------------------------
# 选 Caddy 而非 nginx+certbot：自动签发/续期 Let's Encrypt 证书，
# OEM 自部零证书运维——这是发行版“一条命令装完”的关键简化。
# 单域名同源：前端、Matrix API、cosmac API 全在 https://{{DOMAIN}} 下，
# 客户端按同源自动找到 homeserver（见 client/src/config/hs.ts）。
# ============================================================

{
	# ACME 联系邮箱（证书到期提醒发这里）
	email {{ADMIN_EMAIL}}
	# 信任私网上游反代还原真实客户端 IP(与 -proxy 模板同因:防登录限频误伤)。
	# 直出模式下客户端是公网直连、不落私网段,此项不影响、纯为共存部署兜底。
	servers {
		trusted_proxies static private_ranges
	}
}

{{DOMAIN}} {
	encode zstd gzip

	# —— Matrix 协议层（🚫 路径一个字都不能改，见 CLAUDE.md §7）——
	# 仅放行 client-server/联邦 API 与 /_synapse/client（密码重置等页面）；
	# /_synapse/admin 不对公网暴露（bot 走容器内网访问，不经这里）。
	@matrix path /_matrix/* /_synapse/client/* /_synapse/admin/*
	handle @matrix {
		reverse_proxy synapse:8008
	}

	# —— GuDuu OS 自有 API（注册验码/入驻/商城/皮肤等，bot 提供）——
	# 真实客户端 IP 经 X-Real-IP 传给 bot(登录限频/异地检测/审计用)。
	handle /cosmac/* {
		reverse_proxy bot:9000 {
			header_up X-Real-IP {client_ip}
		}
	}

	# —— 联邦服务发现：联邦走 443（免开 8448 端口）——
	handle /.well-known/matrix/server {
		header Content-Type application/json
		respond `{"m.server": "{{DOMAIN}}:443"}` 200
	}

	# —— 客户端服务发现：homeserver 即本域名 ——
	handle /.well-known/matrix/client {
		header Content-Type application/json
		header Access-Control-Allow-Origin *
		respond `{"m.homeserver": {"base_url": "https://{{DOMAIN}}"}}` 200
	}

	# —— 构建产物（文件名自带内容哈希）——
	# ⚠️ 必须排在通配 handle **之前**，且**不做 SPA 回退**：文件不存在就该老实 404。
	# 若回退成 index.html，浏览器会拿着 HTML 当 JS 解析、动态 import 静默失败，
	# 表现是「点了没反应」而非报错，极难排查（负责人实报「添加账号点了没反应」，
	# 根因正是浏览器缓存着旧 index.html → 请求已被新构建删除的 chunk → 被回退成 HTML）。
	# 文件名带哈希，内容一变名字就变，所以可以放心永久缓存。
	handle /assets/* {
		root * /srv
		header Cache-Control "public, max-age=31536000, immutable"
		file_server
	}

	# —— 前端静态（hash 路由，深链统一回 index.html）——
	handle {
		root * /srv
		# index.html 绝不能被缓存：它是「本次构建用哪套 chunk」的唯一索引。
		# 一旦被浏览器缓存住，用户会一直引用上个版本的 chunk（部署后已删除）。
		# 之前这里没有任何 Cache-Control，浏览器按启发式缓存了数小时。
		header Cache-Control "no-cache"
		try_files {path} /index.html
		file_server
	}
}
