# Third-party notices

根目录 `LICENSE` 仅适用于本项目贡献者拥有权利的代码，不替代第三方组件、模型、图片、字体或资料的原始许可。

## 讯飞 xrtc / 虚拟人 SDK

`frontend/src/vendor/avatar-sdk-web/esm/xrtc-player-BwBCNQ7H.js` 与 `admin-web/src/vendor/avatar-sdk-web/esm/xrtc-player-BwBCNQ7H.js` 的内置头部为：

```text
xrtc.js v5.2024.5.0_00
(c) 2020-2024
Released under the MIT License in iflytek.
```

对应目录的 `LICENSE-xrtc.txt` 保留该头部并包含完整 MIT 许可文本。版本和许可声明直接来自文件头部，没有添加额外版权归属。

原始 SDK 下载地址、随包许可文件以及其他打包模块的完整来源与传递许可链未能仅从仓库文件确认。再次分发前，应与讯飞官方发行包核对，不以根目录 MIT 许可证替代这些条款。

## WebRTC adapter

两个前端的 `webrtc-player-DDFt_Fdy.js` 包含 WebRTC adapter 模块，上游项目为 [webrtcHacks/adapter](https://github.com/webrtcHacks/adapter)。具体打包版本未能从压缩文件确认。对应目录的 `LICENSE-webrtc-adapter.txt` 包含上游 BSD 许可文本。

## 软件杯公开资料包

规范化知识资料的来源、原始文件哈希和冲突处理记录在 `backend/scripts/a5_official_manifest.json`。来源包括：

- [中国软件杯官方页面](https://www.cnsoftbei.com/content-3-1245-1.html)
- [2026 软件杯 A5 示范景区公开资料包](https://www.cnsoftbei.com/uploadfile/2026/0323/20260323113204906.zip)

公开下载不等同于授予任意再分发权。资料包没有在本仓库中发现单独的再分发许可，因此不对原始资料或规范化文本附加新的权利声明；后续使用应遵守主办方和资料权利方条款。

## 项目生成图片

当前默认用户头像与五个角色卡片头像由本项目生成的抽象字母图形组成，不使用真人照片。景区主图仅保留远景，已裁去近景游客。运行期游客上传与数字人预览截图不纳入仓库跟踪。
