# NIS 许可归属与适配说明（P3 / session p3-001）

- 算法：**NVIDIA Image Scaling v1.0.2（NIS，含 NIS 锐化段）**，MIT 许可。
- 资源：`shaders/p3-NIS.glsl` —— 以 `docs/证据/port-NVScaler.glsl`
  （NVIDIA v1.0.2，agyild 的 mpv 移植，MIT 版权头内嵌）为基的适配版
  （p3-adapt-v1）。
- 基文件 SHA-256：`bac778ec0108d272e4dad97794a3c257e65bbebd52aa762f95bce930cbd6b73c`
  （来源取证：`docs/证据/移植取证索引.json`；本阶段未从网络重新下载）。
- 许可文本核对记录（只读引用）：NVIDIA MIT 原文内嵌于基文件与适配版头部，
  原版权声明（Copyright(c) 2022 NVIDIA CORPORATION & AFFILIATES）完整保留。
- 归属：NVIDIA CORPORATION & AFFILIATES（算法与参考实现）；mpv 移植 by
  agyild。本仓库副本完整保留原版权与 MIT 许可声明。

## 适配范围（逐条记录；主算法/系数/workgroup 布局零改动）

1. **每像素输出边界 guard（版本化新增，`nis_bounds_guard`）**：原 port 末尾
   `imageStore` 无显式边界检查。P3 适配在 **全部 groupMemoryBarrier/barrier
   之后** 增加逐像素 `dstX/dstY ∈ [0, imageSize(out_image))` 判定，仅跳过
   末组非整除 tile 的越界写入；**任何线程不得在组 barrier 前 return**
   （guard 形态=全体线程执行 barrier 后按像素条件跳过写）。理由与审计：
   - compute dispatch 的工作组数为 `ceil(输出/32) × ceil(输出/24)`，输出尺寸
     非 32×24 整除时末组线程的 dstX/dstY 超出图像（CPU 索引复算证明：如
     100×70 输出 → 无 guard 越界写入 >0 次；有 guard = 0 次）；
   - 共享内存读/写界限审计：tile 装载循环与输出循环使用同一 numTile 推导，
     读地址不会超出已写区域；共享数组容量（kTileSize=(32+6)×(24+6)）仅在
     **单轴缩小**（kScale>1）时可能被参考自身的 tile 尺寸推导超出——此为
     参考实现固有性质，`//!WHEN`（仅面积放大生效）使常规放大场景远离该
     边界；本适配不修改参考的装载算法，仅在实现说明中如实披露。
2. **溯源注释块（仅注释；无任何指令样前缀行）**：标记 p3-adapt-v1、基文件
   路径与哈希、guard 说明；指令行（HOOK/BIND/DESC/COMPUTE/WHEN/WIDTH/
   HEIGHT/TEXTURE）与算法体零改动。
3. **//!WHEN 原样保留**：`OUTPUT.w OUTPUT.h * LUMA.w LUMA.h * / 1.0 >`
   （仅 >1× 放大生效）不改——等尺寸/缩小场景按 WHEN 诚实跳过。
4. **绝不叠加 NVSharpen**：NIS 自带锐化段；`port-NVSharpen.glsl`
   （sha256 3d51ac2a…）仅作溯源对照，不产生任何 P3 资源、不进入任何链。
5. 系数纹理 `coef_scaler`/`coef_usm`（2×64 rgba32f）与基文件字节一致
   （哈希闭环见 `shaders/p3-resource-manifest.json` 与 p3_lib 审计）。

## 已知边界（如实披露）

- `//!WHEN` 保证面积放大；单轴缩小的各向异性极端几何下，共享 tile 容量
  边界为参考实现固有性质（见上），未在本阶段修改参考装载算法。
- GPU 不报错不作为无越界证明；SHD-05 以 CPU 索引复算（OOB 计数）+
  实机 DESC/帧新鲜样本双证。
