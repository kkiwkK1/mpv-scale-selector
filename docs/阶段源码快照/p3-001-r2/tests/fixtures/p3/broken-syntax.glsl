// p3-test broken syntax shader（测试桩：故意语法错误，仅存在于测试隔离配置
// 目录；SHD-13 负例使用。负例身份必须保持，绝不修复。）
//!HOOK MAIN
//!BIND HOOKED
//!DESC p3-test broken (syntax error)
vec4 hook() { return HOOKED_tex(HOOKED_pos) }
