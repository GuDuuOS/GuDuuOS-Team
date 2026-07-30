# ============================================================
# GuDuu OS · 宿主 nginx 的 Matrix 服务发现片段
# ------------------------------------------------------------
# 用法：渲染占位符后，把本文件 include 到 HTTPS server 块中。
# 必须使用精确匹配（location =），以覆盖宝塔等面板自动生成的
# `location /.well-known/` 静态目录规则；否则请求会落到空目录并返回 404。
#
# {{PUBLIC_DOMAIN}}      用户访问客户端/API 的公开域名
# {{MATRIX_SERVER_NAME}} Synapse 的真实 server_name（用户 ID 冒号后的域名）
# ============================================================

location = /.well-known/matrix/client {
    default_type application/json;
    add_header Access-Control-Allow-Origin "*" always;
    add_header Cache-Control "public, max-age=3600" always;
    add_header X-Content-Type-Options "nosniff" always;
    # 子 location 自己声明 add_header 后不会继承 server 层 HSTS，因此这里明确补回。
    add_header Strict-Transport-Security "max-age=31536000" always;
    return 200 '{"m.homeserver":{"base_url":"https://{{PUBLIC_DOMAIN}}"}}';
}

location = /.well-known/matrix/server {
    default_type application/json;
    add_header Access-Control-Allow-Origin "*" always;
    add_header Cache-Control "public, max-age=3600" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Strict-Transport-Security "max-age=31536000" always;
    return 200 '{"m.server":"{{MATRIX_SERVER_NAME}}:443"}';
}
