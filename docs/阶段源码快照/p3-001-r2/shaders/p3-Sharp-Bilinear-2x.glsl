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
 * This file is the MANUAL 2x gear (menu id sharpbilinear2x): the reference
 * parameter SHARP_BILINEAR_PRE_SCALE is fixed to 2.0 (the reference default
 * is 4.0; the separately named 2x gear pins the pre-scale at exactly 2 — a
 * declared, explicit constant, not a new algorithm and not two chained
 * passes). The sample-coordinate math is byte-for-byte the reference's:
 * floor/fract pre-scaled coordinate with the hardware LINEAR interpolator,
 * rendered in ONE pass at the output resolution (AUTO_PRESCALE inactive,
 * i.e. the reference's manual pre-scale branch).
 *   - InputSize maps to the bound MAIN texture size (HOOKED_size).
 *   - this comment block only; no directive-bearing comment lines were added.
 */

//!HOOK MAIN
//!BIND HOOKED
//!DESC Sharp Bilinear (manual 2x)
//!WIDTH OUTPUT.w
//!HEIGHT OUTPUT.h

vec4 hook()
{
    vec2 texel = HOOKED_pos * HOOKED_size;
    vec2 texel_floored = floor(texel);
    vec2 s = fract(texel);

    // reference manual pre-scale branch (SHARP_BILINEAR_PRE_SCALE fixed 2.0)
    float scale = 2.0;
    float region_range = 0.5 - 0.5 / scale;

    // Figure out where in the texel to sample to get correct pre-scaled bilinear.
    // Uses the hardware bilinear interpolator to avoid having to sample 4 times manually.
    vec2 center_dist = s - 0.5;
    vec2 f = (center_dist - clamp(center_dist, vec2(-region_range), vec2(region_range))) * scale + 0.5;

    vec2 mod_texel = texel_floored + f;

    return vec4(HOOKED_tex(mod_texel / HOOKED_size).rgb, 1.0);
}
