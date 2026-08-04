# Microsoft Store 打包占位说明

开发期使用 `GuDuuOS.Desktop.Development` 与 `CN=GuDuu OS Development` 作为本地未签名
MSIX 身份。进入发布期后，必须从 Partner Center 获取正式 Package Identity、Publisher
和显示名称，通过 CI 环境变量注入，不能直接改源码或复用个人测试证书。

正式候选包只能在 Windows CI / Windows 真机生成，并执行 Windows App Certification
Kit。当前目录不保存证书、PFX 密码或 Partner Center 凭据。
