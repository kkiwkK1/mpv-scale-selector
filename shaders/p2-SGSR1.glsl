// p2-SGSR1.glsl — P2 档位资源（session p2-001）
// 适配版资源标识: SGSR1 / 适配版本: p2-adapt-v1（仅头部溯源注释与许可保留，主算法零改动）
// 基文件: docs/证据/port-SGSR.glsl (Qualcomm SGSR1 luma 适配版, agyild mpv 移植, BSD-3-Clause)
// 基文件 SHA-256: 10a3d1ada2c439607caac32de2a5adceab1cd1580261511aaf67bafd415065fe
// 来源 gist raw（取证见 docs/证据/移植取证索引.json）:
//   https://gist.githubusercontent.com/agyild/7715b6b1f38427839d58f80884902cab/raw/c0895842cec8cf23ebaa619529fc53b7d911f12a/SGSR.glsl
// 许可: BSD-3-Clause（Qualcomm 版权头保留于下方原文）；许可核对记录: docs/证据/sgsr-license.txt
// 已知差异（在案记录）: 本移植为 luma 适配版（非 RGB 原版），含 2025-12-23 hotfix；
//   亮度通道处理与原版 RGB 处理存在适配差异，如实记录，不宣称与原版逐像素等价。
// 适配差异（本文件相对基文件的全部改动，均不触及主算法）:
//   * 仅在本头部追加溯源/适配说明注释；
//   * !PARAM 全部使用文件内固定值（UseEdgeDirection=1, EdgeThreshold=4.0,
//     EdgeSharpness=2.0，均在声明 MINIMUM/MAXIMUM 范围内），不开放运行时改写；
//   * 保留 !WHEN（仅放大时运行）与 OUTPUT.w/OUTPUT.h 目标尺寸。
//   * 2026-10-03 解析修复（p2-001 接续实测根因）: mpv 0.40/libplacebo v7.357 的
//     user shader 解析器会把注释行中出现的指令样文字（叹号+斜杠前缀的
//     PARAM/WHEN 等字样）误当作真实指令，注入伪 !PARAM 块后因缺少类型声明而
//     报 "Missing variable type!" 拒载整文件；本头部注释内的此类文字已去
//     前缀。真实指令行（下方 !PARAM/!HOOK/!WHEN 等）与算法主体零改动。
// 本文件由 P2 实施流程生成并记录于 shaders/resource-manifest.json（含独立 SHA-256）。

//============================================================================================================
//
//
//                  Copyright (c) 2023, Qualcomm Innovation Center, Inc. All rights reserved.
//                              SPDX-License-Identifier: BSD-3-Clause
//
//============================================================================================================

// Snapdragon Game Super Resolution (GSR) v1 by Qualcomm
// ported to mpv by agyild

// Changelog
// 2025-07-13 - Initial release
// - Now operates on the luma channel (instead of green) for improved accuracy.
// - Removed the redundant "Operation mode" variable.
// - Optimized code for readability and a minor performance gain.
//
// 2025-12-23 - Hotfix
// - Fixed the std calculation for non-Edge Direction branch of the code;
//   the previous one was using the Edge Direction variant, causing it
//   to produce blurry output.

//!PARAM UseEdgeDirection
//!DESC Enables the direction-aware upscaling algorithm. This is critical for quality, as it preserves sharp edges by avoiding blurring across them. Disabling it falls back to a simpler and faster filter.
//!TYPE DEFINE
//!MINIMUM 0
//!MAXIMUM 1
1

//!PARAM EdgeThreshold
//!DESC Controls the sensitivity of the edge detection. The sharpening logic is only applied to areas considered an "edge". Higher values increase performance by processing fewer pixels but may miss subtle details. Lower values process more of the image, increasing detail at the cost of performance and potentially amplifying noise.
//!TYPE CONSTANT float
//!MINIMUM 1.0
//!MAXIMUM 16.0
4.0

//!PARAM EdgeSharpness
//!DESC Controls the strength of the sharpening effect applied to detected edges. Higher values create a sharper, more pronounced image but can introduce "ringing" or halo artifacts if set too high. This setting has no impact on performance.
//!TYPE CONSTANT float
//!MINIMUM 1.0
//!MAXIMUM 2.0
2.0

//!HOOK LUMA
//!BIND HOOKED
//!DESC Snapdragon Game Super Resolution (GSR) v1
//!WHEN OUTPUT.w OUTPUT.h * HOOKED.w HOOKED.h * / 1.0 >
//!WIDTH OUTPUT.w
//!HEIGHT OUTPUT.h
//!COMPONENTS 1

// Shader code

float fastLanczos2(float x)
{
	float wA = x - 4.0;
	float wB = x * wA - wA;
	wA *= wA;
	return wB * wA;
}

#if (UseEdgeDirection == 1)
vec2 weightY(float dx, float dy, float c, vec3 data)
#else
vec2 weightY(float dx, float dy, float c, float data)
#endif
{
#if (UseEdgeDirection == 1)
	float std = data.x;
	vec2 dir = data.yz;

	float edgeDis = ((dx * dir.y) + (dy * dir.x));
	float x = fma(edgeDis * edgeDis, (clamp(c * c * std, 0.0, 1.0) * 0.7 - 1.0), (dx * dx + dy * dy));
#else
	float std = data;
	float x = fma((dx * dx + dy * dy), 0.55, clamp(abs(c) * std, 0.0, 1.0));
#endif

	float w = fastLanczos2(x);
	return vec2(w, w * c);
}

vec2 edgeDirection(vec4 left, vec4 right)
{
	vec2 delta;
	delta.x = (right.x - left.z) + (right.w - left.y);
	delta.y = (right.x - left.z) - (right.w - left.y);
	return delta * inversesqrt(dot(delta, delta) + 3.075740e-05);
}

vec4 hook()
{
	vec4 color = HOOKED_texOff(0);

	vec2 imgCoord = ((HOOKED_pos * HOOKED_size) + vec2(-0.5, 0.5));
	vec2 imgCoordPixel = floor(imgCoord);
	vec2 coord = (imgCoordPixel * HOOKED_pt);
	vec2 pl = (imgCoord + (-imgCoordPixel));
	vec4 left = HOOKED_gather(coord, 0);

	float edgeVote = abs(left.z - left.y) + abs(color.x - left.y)  + abs(color.x - left.z) ;
	if (edgeVote > (EdgeThreshold / 255))
	{
		coord.x += HOOKED_pt.x;

		vec4 right = HOOKED_gather(coord + vec2(HOOKED_pt.x, 0.0), 0);
		vec4 upDown;
		upDown.xy = HOOKED_gather(coord + vec2(0.0, -HOOKED_pt.y), 0).wz;
		upDown.zw  = HOOKED_gather(coord+ vec2(0.0, HOOKED_pt.y), 0).yx;

		float mean = (left.y + left.z + right.x + right.w) * 0.25;
		left -= vec4(mean);
		right -= vec4(mean);
		upDown -= vec4(mean);
		color.w = color.x - mean;

		float sum = dot(abs(left) + abs(right) + abs(upDown), vec4(1.0));

#if (UseEdgeDirection == 1)
		float sumMean = 1.014185e+01 / sum;
		float std = sumMean * sumMean;
		vec3 data = vec3(std, edgeDirection(left, right));
#else
		float std = 2.181818 / sum;
		float data = std;
#endif
		vec2 aWY  = weightY(pl.x,       pl.y + 1.0, upDown.x, data);
		     aWY += weightY(pl.x - 1.0, pl.y + 1.0, upDown.y, data);
		     aWY += weightY(pl.x - 1.0, pl.y - 2.0, upDown.z, data);
		     aWY += weightY(pl.x,       pl.y - 2.0, upDown.w, data);
		     aWY += weightY(pl.x + 1.0, pl.y - 1.0,   left.x, data);
		     aWY += weightY(pl.x,       pl.y - 1.0,   left.y, data);
		     aWY += weightY(pl.x,       pl.y,         left.z, data);
		     aWY += weightY(pl.x + 1.0, pl.y,         left.w, data);
		     aWY += weightY(pl.x - 1.0, pl.y - 1.0,  right.x, data);
		     aWY += weightY(pl.x - 2.0, pl.y - 1.0,  right.y, data);
		     aWY += weightY(pl.x - 2.0, pl.y,        right.z, data);
		     aWY += weightY(pl.x - 1.0, pl.y,        right.w, data);

		float finalY = aWY.y / aWY.x;
		float maxY = max(max(left.y, left.z), max(right.x, right.w));
		float minY = min(min(left.y, left.z), min(right.x, right.w));
		float deltaY = clamp(EdgeSharpness * finalY, minY, maxY) - color.w;

		//smooth high contrast input
		deltaY = clamp(deltaY, -23.0 / 255.0, 23.0 / 255.0);

		color.x = clamp((color.x + deltaY), 0.0, 1.0);
	}

	color.w = 1.0;

	return color;
}