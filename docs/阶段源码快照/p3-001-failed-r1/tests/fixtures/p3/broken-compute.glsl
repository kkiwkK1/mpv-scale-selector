// p3-test broken compute shader（测试桩：故意 compute 编译失败，仅存在于测试
// 隔离配置目录；SHD-05/SHD-13 负例使用。负例身份必须保持，绝不修复。）
// 基于合法 compute 形态，但引用未声明的共享数组与未定义函数 → 真实编译错误。
//!HOOK LUMA
//!BIND HOOKED
//!DESC p3-test broken compute (compile error)
//!COMPUTE 32 24 256 1
//!WIDTH OUTPUT.w
//!HEIGHT OUTPUT.h

shared float shP3TestBroken[kUndefinedTileSize];

vec4 hook()
{
    shP3TestBroken[0] = undefinedFunctionNotDeclared(HOOKED_pos);
    return HOOKED_tex(HOOKED_pos);
}
