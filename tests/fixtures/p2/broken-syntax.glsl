// p2-test broken shader（测试桩：故意语法错误——缺分号，仅存在于测试隔离配置目录）
// 专用途：SHD-13 编译失败回退验证。绝不进入发布目录 shaders/。
//!HOOK LUMA
//!BIND HOOKED
//!DESC p2-test broken (syntax error)
vec4 hook() { return HOOKED_tex(HOOKED_pos) }
