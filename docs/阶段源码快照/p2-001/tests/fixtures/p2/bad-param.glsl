// p2-test incompatible-PARAM shader（测试桩：//!PARAM 值超出声明 MAXIMUM，
// 仅存在于测试隔离配置目录）
// 专用途：SHD-13 不兼容 PARAM（mpv 静默拒绝加载）验证。绝不进入发布目录 shaders/。
//!PARAM TESTLEVEL
//!DESC p2-test bad param (value out of declared range)
//!TYPE CONSTANT float
//!MINIMUM 0.0
//!MAXIMUM 1.0
42.0
//!HOOK LUMA
//!BIND HOOKED
vec4 hook() { return HOOKED_tex(HOOKED_pos); }
