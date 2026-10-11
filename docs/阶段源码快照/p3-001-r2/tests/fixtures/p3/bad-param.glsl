// p3-test incompatible PARAM shader（测试桩：PARAM 值超出声明范围，仅存在于
// 测试隔离配置目录；SHD-13 负例使用。负例身份必须保持，绝不修复。）
//!PARAM P3TESTLEVEL
//!DESC p3-test bad param
//!TYPE CONSTANT float
//!MINIMUM 0.0
//!MAXIMUM 1.0
42.0
//!HOOK MAIN
//!BIND HOOKED
vec4 hook() { return HOOKED_tex(HOOKED_pos); }
