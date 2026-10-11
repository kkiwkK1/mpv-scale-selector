/*
 * sharp-bilinear
 * Author: Themaister
 * License: Public domain
 *
 * Does a bilinear stretch, with a preapplied Nx nearest-neighbor scale, giving a
 * sharper image than plain bilinear.
 */

/*
 * P3 adaptation marker: p3-adapt-v1 (session p3-001).
 * Provenance: ported from the forensic base file
 * docs/证据/sharp-bilinear.glsl,
 * sha256 9b9afa91fe12bcbd49398179bf2072ce5a38b531c39a4fd381e92602c6dc114b
 * (Themaister sharp-bilinear, public domain). The original header above is
 * preserved verbatim.
 *
 * This file is the AUTO gear (menu id sharpbilinear): the reference parameter
 * AUTO_PRESCALE is fixed to its active value (>0.5), so the scale is the
 * reference formula floor(outsize.y / InputSize.y + 0.01) evaluated at the
 * current output geometry.
 *   - mpv hook adaptation: this mpv/libplacebo build exposes no output-size
 *     uniform to user shaders, so outsize.y / InputSize.y is re-derived per
 *     pixel as gl_FragCoord.y / (HOOKED_pos.y * HOOKED_size.y) — the identical
 *     ratio at the pixel center (mpv 0.40+gpu-next empirical probe; the
 *     +0.01 reference epsilon also absorbs the float rounding here).
 *   - 1080p source in a 1440p window gives floor(1.333+0.01)=1: the gear
 *     DEGRADES to plain bilinear in that window (declared honestly in the
 *     menu/OSD note; the formula and its epsilon are the reference's own).
 *   - P3 adaptation: the computed scale is clamped to >= 1. The reference's
 *     region_range = 0.5 - 0.5/scale divides by the scale and would produce
 *     NaN/undefined behaviour at scale=0 (output smaller than input); scale=1
 *     is the defined plain-bilinear degenerate used as the safe fallback.
 *   - InputSize maps to the bound MAIN texture size (HOOKED_size); the pass
 *     renders in ONE pass at the output resolution, sampling the source with
 *     the reference's pre-scale coordinate mapping (hardware LINEAR), not two
 *     chained passes.
 *   - this comment block only; no directive-bearing comment lines were added.
 */

//!HOOK MAIN
//!BIND HOOKED
//!DESC Sharp Bilinear (AUTO)
//!WIDTH OUTPUT.w
//!HEIGHT OUTPUT.h

vec4 hook()
{
    vec2 texel = HOOKED_pos * HOOKED_size;
    vec2 texel_floored = floor(texel);
    vec2 s = fract(texel);

    // outsize.y / InputSize.y re-derived at the pixel center (see header):
    float out_over_in = gl_FragCoord.y / (HOOKED_pos.y * HOOKED_size.y);
    // reference AUTO formula (AUTO_PRESCALE > 0.5 branch)
    float scale = floor(out_over_in + 0.01);
    // P3 adaptation: scale < 1 (including the 0 case) cannot drive the
    // region_range division — clamp to the defined plain-bilinear degenerate
    scale = max(scale, 1.0);
    float region_range = 0.5 - 0.5 / scale;

    // Figure out where in the texel to sample to get correct pre-scaled bilinear.
    // Uses the hardware bilinear interpolator to avoid having to sample 4 times manually.
    vec2 center_dist = s - 0.5;
    vec2 f = (center_dist - clamp(center_dist, vec2(-region_range), vec2(region_range))) * scale + 0.5;

    vec2 mod_texel = texel_floored + f;

    return vec4(HOOKED_tex(mod_texel / HOOKED_size).rgb, 1.0);
}
