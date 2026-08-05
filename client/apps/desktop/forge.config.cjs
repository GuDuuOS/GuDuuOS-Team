const path = require('node:path')
const fs = require('node:fs/promises')

const { MakerDMG } = require('@electron-forge/maker-dmg')
const { MakerMSIX } = require('@electron-forge/maker-msix')
const { MakerSquirrel } = require('@electron-forge/maker-squirrel')
const { MakerZIP } = require('@electron-forge/maker-zip')
const { flipFuses, FuseV1Options, FuseVersion } = require('@electron/fuses')
const plist = require('plist')
const electronChecksums = require('./node_modules/electron/checksums.json')

const desktopRoot = __dirname
const iconBase = path.join(desktopRoot, 'assets', 'icon')
const isMas = process.env.GUDUU_DESKTOP_TARGET === 'mas'
const macIdentity = process.env.GUDUU_MAC_SIGN_IDENTITY
const macProvisioningProfile = process.env.GUDUU_MAC_PROVISIONING_PROFILE

/**
 * 生成 macOS 签名配置。
 * 本地构建使用 ad-hoc 签名便于验证包结构；发布期注入真实身份后自动开启 Hardened Runtime。
 * MAS 主程序拿最小沙盒权限，所有 Helper 只继承，避免子进程意外扩大能力范围。
 */
function macSignConfig() {
  const isDevelopmentAdHocSignature = !macIdentity
  const appEntitlements = path.join(desktopRoot, 'store/macos/entitlements.mas.plist')
  const inheritedEntitlements = path.join(
    desktopRoot,
    'store/macos/entitlements.mas.inherit.plist'
  )
  const config = {
    identity: macIdentity || '-',
    identityValidation: Boolean(macIdentity),
    ...(macProvisioningProfile ? { provisioningProfile: macProvisioningProfile } : {})
  }

  config.optionsForFile = (filePath) => {
    const normalizedPath = filePath.replace(/[\\/]+$/, '')
    const isTopLevelAppBundle =
      normalizedPath.endsWith('.app') &&
      normalizedPath.indexOf('.app') === normalizedPath.lastIndexOf('.app')
    const isTopLevelMainExecutable =
      normalizedPath.endsWith('/Contents/MacOS/GuDuu OS') &&
      normalizedPath.indexOf('.app') === normalizedPath.lastIndexOf('.app')

    return {
      hardenedRuntime: !isDevelopmentAdHocSignature,
      ...(isMas
        ? {
            entitlements: isTopLevelAppBundle || isTopLevelMainExecutable
              ? appEntitlements
              : inheritedEntitlements
          }
        : {})
    }
  }

  return config
}

/**
 * Electron 模板自带若干硬件权限文案，但当前客户端只使用文件选择器。
 * 在签名前移除未使用的音频、蓝牙、摄像头和麦克风声明，避免误导用户和商店审核。
 */
function stripUnusedMacPermissionDescriptions(buildPath, _version, platform, _arch, done) {
  if (platform !== 'darwin' && platform !== 'mas') {
    done()
    return
  }

  const infoPath = path.join(buildPath, 'Electron.app', 'Contents', 'Info.plist')
  fs.readFile(infoPath, 'utf8')
    .then((source) => {
      const info = plist.parse(source)
      delete info.NSAudioCaptureUsageDescription
      delete info.NSBluetoothAlwaysUsageDescription
      delete info.NSBluetoothPeripheralUsageDescription
      delete info.NSCameraUsageDescription
      delete info.NSMicrophoneUsageDescription
      return fs.writeFile(infoPath, plist.build(info))
    })
    .then(() => done(), done)
}

const windowsCertificate = process.env.WINDOWS_CERTIFICATE_FILE
const windowsCertificatePassword = process.env.WINDOWS_CERTIFICATE_PASSWORD
const windowsSignOptions = windowsCertificate
  ? {
      certificateFile: windowsCertificate,
      ...(windowsCertificatePassword
        ? { certificatePassword: windowsCertificatePassword }
        : {})
    }
  : undefined

module.exports = {
  packagerConfig: {
    asar: true,
    prune: true,
    download: { checksums: electronChecksums },
    appBundleId: 'co.guduu.os.desktop',
    appCategoryType: 'public.app-category.business',
    appCopyright: 'Copyright © GuDuu OS',
    executableName: 'GuDuu OS',
    icon: iconBase,
    ignore: [
      /^\/\.gitignore$/,
      /^\/assets(?:\/|$)/,
      /^\/out(?:\/|$)/,
      /^\/scripts(?:\/|$)/,
      /^\/store(?:\/|$)/,
      /^\/tests(?:\/|$)/,
      /^\/forge\.config\.cjs$/,
      /^\/README\.md$/,
      /^\/package-lock\.json$/
    ],
    protocols: [{ name: 'GuDuu OS Link', schemes: ['guduu'] }],
    extendInfo: {
      NSHighResolutionCapable: true,
      NSAppTransportSecurity: { NSAllowsArbitraryLoads: false }
    },
    win32metadata: {
      CompanyName: 'GuDuu OS',
      FileDescription: 'GuDuu OS Desktop',
      ProductName: 'GuDuu OS',
      InternalName: 'GuDuuOS',
      'requested-execution-level': 'asInvoker'
    },
    osxSign: macSignConfig(),
    afterExtract: [stripUnusedMacPermissionDescriptions],
    ...(windowsSignOptions ? { windowsSign: windowsSignOptions } : {})
  },
  rebuildConfig: {},
  hooks: {
    packageAfterCopy: async (_forgeConfig, resourcesPath, _electronVersion, platform) => {
      // Fuses 必须在签名前写入可执行文件；开启 ASAR 完整性并关闭 Node/调试逃生口。
      const isApplePlatform = platform === 'darwin' || platform === 'mas'
      const executableBasePath = path.resolve(resourcesPath, '../..')
      const executablePath = isApplePlatform
        ? path.join(executableBasePath, 'MacOS', 'Electron')
        : path.join(executableBasePath, `electron${platform === 'win32' ? '.exe' : ''}`)

      await flipFuses(executablePath, {
        version: FuseVersion.V1,
        strictlyRequireAllFuses: true,
        [FuseV1Options.RunAsNode]: false,
        [FuseV1Options.EnableCookieEncryption]: true,
        [FuseV1Options.EnableNodeOptionsEnvironmentVariable]: false,
        [FuseV1Options.EnableNodeCliInspectArguments]: false,
        [FuseV1Options.EnableEmbeddedAsarIntegrityValidation]: true,
        [FuseV1Options.OnlyLoadAppFromAsar]: true,
        [FuseV1Options.LoadBrowserProcessSpecificV8Snapshot]: false,
        [FuseV1Options.GrantFileProtocolExtraPrivileges]: false,
        [FuseV1Options.WasmTrapHandlers]: true
      })
    }
  },
  makers: [
    new MakerDMG(
      {
        name: 'GuDuu OS',
        icon: `${iconBase}.icns`,
        overwrite: true,
        format: 'ULFO'
      },
      ['darwin']
    ),
    new MakerZIP({}, ['darwin']),
    new MakerSquirrel(
      {
        name: 'GuDuuOS',
        authors: 'GuDuu OS',
        description: 'GuDuu OS desktop client',
        setupIcon: `${iconBase}.ico`,
        iconUrl: 'https://www.guduu.co/favicon.ico',
        noMsi: true,
        ...(windowsSignOptions
          ? {
              certificateFile: windowsCertificate,
              certificatePassword: windowsCertificatePassword
            }
          : {})
      },
      ['win32']
    ),
    new MakerMSIX(
      {
        packageName: 'GuDuuOS',
        sign: process.env.GUDUU_WINDOWS_SIGN === '1',
        ...(windowsSignOptions ? { windowsSignOptions } : {}),
        manifestVariables: {
          packageIdentity:
            process.env.GUDUU_MSIX_IDENTITY || 'GuDuuOS.Desktop.Development',
          publisher: process.env.GUDUU_MSIX_PUBLISHER || 'CN=GuDuu OS Development',
          publisherDisplayName: 'GuDuu OS',
          packageDisplayName: 'GuDuu OS',
          packageDescription: 'GuDuu OS desktop client',
          appDisplayName: 'GuDuu OS',
          packageBackgroundColor: 'transparent',
          packageMinOSVersion: '10.0.19041.0',
          packageMaxOSVersionTested: '10.0.26100.0'
        }
      },
      ['win32']
    )
  ]
}
