# scale-selector — mpv 缩放算法选择器 / Scaling Algorithm Selector for mpv

[English](README_EN.md) | [简体中文](README_CN.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/kkiwkK1/mpv-scale-selector/blob/main/LICENSE)
[![Release](https://img.shields.io/badge/Release-v0.1.0-blue)](https://github.com/kkiwkK1/mpv-scale-selector/releases)
[![mpv](https://img.shields.io/badge/mpv-tested%20v0.40.0--393-green)](https://mpv.io)
[![Lua](https://img.shields.io/badge/Lua-LuaJIT%20%7C%205.2%2B-orange)](https://www.lua.org)

**中文**：F8 打开菜单，一键切换 mpv 缩放档位——关 + 9 个真实内建档位，外加 LS1、BCAS 两个诚实禁用占位。托管属性快照恢复、外部改动让出、着色链逐一验证，菜单如实反映真实生效状态（「诚实显示」是设计底线）。

**English**: A scaling-gear selector for [mpv](https://mpv.io). Press **F8** to switch between 9 real built-in gears — AMD FSR1, NVIDIA NIS, Qualcomm SGSR1, Anime4K v4, Hyllian xBR-lv2, Sharp Bilinear (AUTO / 2×), Integer, Nearest — plus two permanently disabled honest placeholders (LS1, BCAS). The menu shows only the truth: guards, skip reasons, per-pass chain verification, automatic rollback.

## 快速安装 / Quick Install (Windows)

先 `git clone` 本仓库（或从 [Releases](https://github.com/kkiwkK1/mpv-scale-selector/releases) 下载 Source code zip 解压），在仓库根目录运行
/ Clone first (or unzip the Release source), then from the repository root run:

```
powershell -ExecutionPolicy Bypass -File tools\install.ps1
```

手工安装（复制三组文件）与安装器退出码：见完整文档
/ Manual install (copy three file groups) and installer exit codes: see the full docs below.

## 档位 / Gears

关 Off · FSR1 · NIS · SGSR1 · Anime4K · xBR · Sharp Bilinear AUTO · Sharp Bilinear 2× · Integer · Nearest（另有两个永久禁用的诚实占位 / plus two permanently disabled honest placeholders: LS1 · BCAS）

## 完整文档 / Full Documentation

- **[简体中文完整文档 — 系统要求、12 档总表、诚实显示、质量保障、FAQ](README_CN.md)**
- **[English full documentation — requirements, 12-gear table, honest display, quality assurance, FAQ](README_EN.md)**

## License

项目代码 MIT；内嵌第三方 shader 保留各自许可（FSR1/NIS MIT、SGSR1 BSD-3-Clause、Anime4K MIT ×8 + Unlicense ×2、xBR MIT、Sharp Bilinear public domain），详见 `licenses/` 目录
/ Project code MIT; bundled third-party shaders keep their own licenses — see the `licenses/` directory.
