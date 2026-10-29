// Weather: the backend-neutral part (see weather.h).
#include "weather.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "../game_addresses.h"
#include "../hle.h"
#include "../menu_sfx.h"
#include "../settings.h"

extern int game_in_play(void);                 // runtime/hle/warp.c
extern int cosmetics_seed_weather(void);       // runtime/cosmetics_seed.c
extern bool widescreen_frame_boxed(uint64_t frame);  // runtime/hle/widescreen.c (indoors: the interior backdrop)
extern void input_rumble_pulse(uint16_t lo, uint16_t hi, uint32_t ms);  // runtime/hle/input.c

static float g_cam[80];  // the frame's camera block (weather_scene_camera)
static uint64_t g_cam_frame = ~0ull;

void weather_scene_camera(const float *u, uint64_t size, uint64_t frame) {
    if (size != 320 || g_cam_frame == frame) return;  // (the frame's first scene draw)
    if (u[12] != 0 || u[13] != 0 || u[14] != 0 || u[15] != 1 || u[30] != -1 || u[31] != 0) return;  // perspective
    memcpy(g_cam, u, sizeof g_cam);
    g_cam_frame = frame;
}

// LARECOMP_WEATHER=off|rain|snow|storm|random (test): instead of the setting
static int setting(void) {
    static int env = -2;
    if (env == -2) {
        const char *e = getenv("LARECOMP_WEATHER");
        static const char *const k[] = {"off", "rain", "snow", "storm", "random"};
        env = -1;
        for (int i = 0; e && i < 5; i++) if (!strcmp(e, k[i])) env = i;
    }
    return env >= 0 ? env : g_settings.weather;
}

static uint32_t mix32(uint32_t h) {
    h ^= h >> 16; h *= 0x7FEB352Du; h ^= h >> 15; h *= 0x846CA68Bu; h ^= h >> 16;
    return h;
}

static int g_random = WEATHER_OFF;  // Random: rolled each time the overworld is entered
static bool g_outdoors;

int weather_current(void) {
    int s = setting();
    if (s == WEATHER_RANDOM) return g_random;
    if (s != WEATHER_OFF) return s;
    static int seed_w;
    static uint64_t at;  // (the seed's pick: looked up once a second, it only changes with the seed)
    uint64_t now = (uint64_t)time(NULL);
    if (now != at) at = now, seed_w = cosmetics_seed_weather();
    return seed_w;
}

static bool level_is_field(void) {
    if (!game_in_play()) return false;
    uint64_t ps = LD64(GA(PLAYER_STATUS_PTR));  // PlayerStatus*: the current level's name at +0
    if (!ps) return false;
    return !strcmp((const char *)(uintptr_t)ps, "Field");
}

// rows: out = a * b
static void mat_mul(const float *a, const float *b, float *out) {
    for (int r = 0; r < 4; r++)
        for (int c = 0; c < 4; c++) {
            float s = 0;
            for (int k = 0; k < 4; k++) s += a[r * 4 + k] * b[k * 4 + c];
            out[r * 4 + c] = s;
        }
}

static bool mat_inverse(const float *m, float *inv) {
    double a[4][8];
    for (int r = 0; r < 4; r++)
        for (int c = 0; c < 8; c++) a[r][c] = c < 4 ? m[r * 4 + c] : (c - 4 == r);
    for (int c = 0; c < 4; c++) {
        int p = c;
        for (int r = c + 1; r < 4; r++) if (fabs(a[r][c]) > fabs(a[p][c])) p = r;
        if (fabs(a[p][c]) < 1e-12) return false;
        if (p != c) for (int k = 0; k < 8; k++) { double t = a[c][k]; a[c][k] = a[p][k]; a[p][k] = t; }
        double d = a[c][c];
        for (int k = 0; k < 8; k++) a[c][k] /= d;
        for (int r = 0; r < 4; r++)
            if (r != c && a[r][c] != 0) {
                double f = a[r][c];
                for (int k = 0; k < 8; k++) a[r][k] -= f * a[c][k];
            }
    }
    for (int r = 0; r < 4; r++)
        for (int c = 0; c < 4; c++) inv[r * 4 + c] = (float)a[r][c + 4];
    return true;
}

// The world point at clip-space (x, y) on the plane y = py (false: the ray misses it)
static bool unproject_floor(const float *inv, float x, float y, float py, float out[3]) {
    float n[4], f[4];
    for (int r = 0; r < 4; r++) {
        n[r] = inv[r * 4 + 0] * x + inv[r * 4 + 1] * y + inv[r * 4 + 2] * -1 + inv[r * 4 + 3];
        f[r] = inv[r * 4 + 0] * x + inv[r * 4 + 1] * y + inv[r * 4 + 2] * 1 + inv[r * 4 + 3];
    }
    if (fabsf(n[3]) < 1e-9f || fabsf(f[3]) < 1e-9f) return false;
    for (int i = 0; i < 3; i++) n[i] /= n[3], f[i] /= f[3];
    float dy = f[1] - n[1];
    if (fabsf(dy) < 1e-6f) return false;
    float t = (py - n[1]) / dy;
    if (t < 0) return false;
    for (int i = 0; i < 3; i++) out[i] = n[i] + (f[i] - n[i]) * t;
    return true;
}

// ---- the storm: lightning flashes and thunder
static double g_next_flash = 4, g_flash_at = -100, g_thunder_at = -1;
static float g_thunder_gain;
static uint32_t g_rng = 0x1234567;
static float frand(void) { g_rng = mix32(g_rng + 0x9E3779B9u); return (g_rng >> 8) / 16777216.0f; }

static float storm_flash(double t, uint64_t frame) {
    static long force_at = -2;  // LARECOMP_WEATHER_FLASH_AT=<frame> (test): a flash then
    if (force_at == -2) force_at = getenv("LARECOMP_WEATHER_FLASH_AT") ? atol(getenv("LARECOMP_WEATHER_FLASH_AT")) : -1;
    if (force_at >= 0 && (long)frame >= force_at) force_at = -1, g_next_flash = t;
    if (t >= g_next_flash) {
        g_flash_at = t;
        g_next_flash = t + 7 + frand() * 14;  // (every 7-21 s)
        float dist = frand();                  // near (0) .. far (1): the thunder's delay and volume
        g_thunder_at = t + 0.3 + dist * 2.2;
        g_thunder_gain = 0.9f - dist * 0.5f;
    }
    if (g_thunder_at >= 0 && t >= g_thunder_at) {
        g_thunder_at = -1;
        menu_sfx_play_gain(MENU_SFX_THUNDER, g_thunder_gain);
        input_rumble_pulse((uint16_t)(g_thunder_gain * 22000), 0, 350);  // (a short low rumble; off with Rumble off)
    }
    // the flash: two quick strobes, then a fade (~0.6 s)
    double a = t - g_flash_at;
    if (a < 0 || a > 0.7) return 0;
    float f = a < 0.06 ? 1.0f : a < 0.12 ? 0.2f : a < 0.18 ? 0.75f : (float)exp(-(a - 0.18) * 12);
    return f;
}

// The probe points (uv in the depth texture: its row 0 at the top) and the world point a probe's depth gives
const float g_weather_probe_uv[WEATHER_PROBES][2] = {{0.5f, 0.5f}, {0.3f, 0.35f}, {0.7f, 0.35f}, {0.3f, 0.65f}, {0.7f, 0.65f}};
bool weather_probe_world(const WeatherFrame *f, int i, float d, float out[3]) {
    if (!(d > 0) || d >= 0.99999f || !(f->zr[1] != 0)) return false;  // (sky / nothing / no probe yet)
    float x = g_weather_probe_uv[i][0] * 2 - 1, y = 1 - g_weather_probe_uv[i][1] * 2;
    if (f->flags[0] > 0.5f) y = -y;
    float z = (d - f->zr[0]) / f->zr[1];
    if (f->flags[1] > 0.5f) z = z * 2 - 1;
    float q[4] = {x, y, z, 1}, r[4];
    for (int k = 0; k < 4; k++) r[k] = f->inv_vp[k * 4] * q[0] + f->inv_vp[k * 4 + 1] * q[1] + f->inv_vp[k * 4 + 2] * q[2] + f->inv_vp[k * 4 + 3];
    if (fabsf(r[3]) < 1e-9f) return false;
    for (int k = 0; k < 3; k++) out[k] = r[k] / r[3];
    return true;
}

bool weather_frame(WeatherFrame *f, uint64_t frame, const float probe[WEATHER_PROBES]) {
    // host time, counted only while the overworld is on screen (a menu or a door stops it)
    static double t = 0, last = 0;
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    double now = ts.tv_sec + ts.tv_nsec * 1e-9, dt = now - last;
    last = now;
    bool field = level_is_field() && !widescreen_frame_boxed(frame);
    if (field && !g_outdoors) {  // (back outside: Random rolls again - clear, rain, snow or storm)
        g_rng ^= (uint32_t)(now * 1000);
        g_random = (int)(frand() * 4) % 4;
        if (setting() == WEATHER_RANDOM) LOG("[weather] random: %d\n", g_random);
    }
    g_outdoors = field;
    int kind = weather_current();
    if (!field || kind == WEATHER_OFF || g_cam_frame != frame) return false;
    if (dt > 0 && dt < 0.25) t += dt;

    // (screen, flags, zr: filled by the renderer)
    memset(f->origin, 0, sizeof f->origin), memset(f->box, 0, sizeof f->box), memset(f->shape, 0, sizeof f->shape);
    memset(f->color, 0, sizeof f->color), memset(f->fill, 0, sizeof f->fill), memset(f->cam, 0, sizeof f->cam);
    f->count = f->splashes = 0;
    f->kind = kind;
    memcpy(f->vp, g_cam + 32, sizeof f->vp);
    if (!mat_inverse(f->vp, f->inv_vp)) return false;
    // the ground's height: the scene depth at a few screen points (probe: the last frame's), their median
    static float ground = 0;
    static uint64_t ground_frame;
    float ys[WEATHER_PROBES];
    int ny = 0;
    for (int i = 0; i < WEATHER_PROBES; i++) {
        float p[3];
        if (probe && weather_probe_world(f, i, probe[i], p)) ys[ny++] = p[1];
    }
    if (ny) {
        for (int i = 1; i < ny; i++)
            for (int j = i; j > 0 && ys[j] < ys[j - 1]; j--) { float x = ys[j]; ys[j] = ys[j - 1]; ys[j - 1] = x; }
        float g = ys[ny / 2];
        // (eased, so a bush or a roof under a probe doesn't jolt the rain; a jump - a new screen - is taken at once)
        ground = fabsf(g - ground) > 6 || frame > ground_frame + 4 ? g : ground + (g - ground) * 0.1f;
        ground_frame = frame;
    }
    // the volume: around the ground point at the screen's centre, of a fixed size (a drop's place in the world comes
    // from its hash, the time and the size only: the volume can follow the view and the ground without moving one)
    float c[3], a[3], b[3];
    if (!unproject_floor(f->inv_vp, 0, 0, ground, c) || !unproject_floor(f->inv_vp, -1, -1, ground, a) ||
        !unproject_floor(f->inv_vp, 1, 1, ground, b))
        return false;
    float w = fabsf(b[0] - a[0]), d = fabsf(b[2] - a[2]);
    // the camera (from the view matrix: -R^T t); the volume stays well below it (drops near the lens would be huge)
    // and leans toward it as the view does (its middle on the centre ray)
    float cp[3];
    for (int i = 0; i < 3; i++) cp[i] = -(g_cam[0 * 4 + i] * g_cam[3] + g_cam[1 * 4 + i] * g_cam[7] + g_cam[2 * 4 + i] * g_cam[11]);
    float cam_h = cp[1] - c[1];
    if (!(cam_h > 1)) return false;
    // (the overworld camera: ~17.7 above the ground, its view ~24 x 19 of it; the volume from 1.5 under the ground to
    // 8.5 over it, half way to the camera)
    const float size = 34, height = 10, mid = height * 0.5f - 1.5f;
    bool snow = kind == WEATHER_SNOW, storm = kind == WEATHER_STORM;
    for (int i = 0; i < 3; i++) f->origin[i] = c[i] + (cp[i] - c[i]) * fminf(mid / cam_h, 0.5f);
    f->origin[3] = ground;
    f->box[0] = size, f->box[1] = height, f->box[2] = (float)fmod(t, 3600.0);
    for (int i = 0; i < 3; i++) f->cam[i] = cp[i];
    // (fall speeds and the wind fixed too: with the time in them, any change would move every drop)
    if (snow) {
        f->count = 2000;
        f->shape[0] = 0, f->shape[1] = 9.0f, f->shape[2] = 2.2f, f->shape[3] = 0.5f;
        f->box[3] = 0.6f;
        f->splashes = f->count;  // (every flake lies where it landed)
        f->cam[3] = 1.5f;  // (for 1.5 s, fading)
        f->color[0] = 0.97f, f->color[1] = 0.98f, f->color[2] = 1.0f, f->color[3] = 0.9f;
        f->fill[3] = 1;  // (no overcast: snow is bright)
    } else {
        f->count = storm ? 2000 : 1300;
        f->splashes = f->count / 3;  // (a ring for every third drop)
        f->shape[0] = storm ? 2.6f : 2.2f, f->shape[1] = 1.9f, f->shape[2] = storm ? 36 : 30;
        f->box[3] = storm ? 8 : 3;
        f->cam[3] = 0.35f;
        f->color[0] = 0.80f, f->color[1] = 0.85f, f->color[2] = 0.95f, f->color[3] = storm ? 0.34f : 0.28f;
        f->fill[3] = storm ? 0.84f : 0.93f;  // (overcast)
        if (storm) {
            float fl = storm_flash(t, frame);
            f->fill[0] = fl * 0.22f, f->fill[1] = fl * 0.25f, f->fill[2] = fl * 0.30f;
            f->fill[3] += (1 - f->fill[3]) * fl;  // (the flash lifts the overcast too)
        }
    }
    f->flags[3] = snow ? 2 : 1;
    static int logged;  // LARECOMP_LOG_WEATHER: the camera and volume (calibration)
    if (getenv("LARECOMP_LOG_WEATHER") && logged++ % 120 == 0)
        LOG("[weather] kind %d ground %.2f (%d probes) centre %.2f %.2f %.2f floor %.2f x %.2f size %.2f height %.2f cam %.2f %.2f %.2f\n", kind, ground, ny, c[0], c[1],
            c[2], w, d, size, height, cp[0], cp[1], cp[2]);
    return true;
}
