// Weather: the backend-neutral part (see weather.h).
#include "weather.h"

#include <math.h>
#include <pthread.h>
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

// ---- snow on the ground (weather.h): the cover, Link's footprints and the snow he kicks up
static double t = 0;   // the weather's time (s): counted only while it shows (weather_frame)
static float g_cover;  // how much snow lies (0..1)
static float env_f(const char *name, float def) { const char *e = getenv(name); return e ? (float)atof(e) : def; }

static pthread_mutex_t g_link_lock = PTHREAD_MUTEX_INITIALIZER;
static float g_link[3];       // Link's position as the game thread read it last (PlayerCollision +0x80: his feet)
static double g_link_at;      // (host time then)
static uint64_t g_link_n;     // (samples so far)

static double host_now(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + ts.tv_nsec * 1e-9;
}

static bool level_is_field(void);
void weather_player_tick(uint64_t frame) {
    if (!g_outdoors || weather_current() != WEATHER_SNOW || !level_is_field()) return;
    extern uint64_t doorjump_player(uint64_t frame);  // runtime/hle/doorjump.c (the PlayerCollision component)
    uint64_t pc = doorjump_player(frame);
    if (!pc) return;
    const float *p = (const float *)(uintptr_t)(pc + 0x80);
    pthread_mutex_lock(&g_link_lock);
    memcpy(g_link, p, sizeof g_link);
    g_link_at = host_now();
    g_link_n++;
    pthread_mutex_unlock(&g_link_lock);
}

static SnowPrint g_prints[64];  // made, not stamped yet (weather_snow_prints)
static int g_nprints;
static SnowPuff g_puffs[SNOW_PUFFS];  // a ring
static int g_puff_next;
static float frand(void);

static void puff(const float at[3], float dx, float dz, bool dash) {
    SnowPuff *q = &g_puffs[g_puff_next++ % SNOW_PUFFS];
    float a = frand() * 6.2832f, r = frand() * (dash ? 0.25f : 0.15f);
    q->p[0] = at[0] + cosf(a) * r, q->p[1] = at[1] + 0.05f, q->p[2] = at[2] + sinf(a) * r, q->p[3] = (float)t;
    float back = dash ? 1.2f + frand() * 1.6f : 0.3f + frand() * 0.6f, side = (frand() - 0.5f) * (dash ? 2.0f : 1.0f);
    q->v[0] = -dx * back - dz * side, q->v[2] = -dz * back + dx * side;  // (behind him, spread sideways)
    q->v[1] = dash ? 1.4f + frand() * 1.6f : 0.7f + frand() * 0.8f;
    q->v[3] = dash ? 9 + frand() * 7 : 6 + frand() * 4;
}

// Footprints and kicked-up snow from Link's latest positions (render thread, once a frame while it shows)
static void snow_link(void) {
    static float lp[3], stride, spd;
    static double lat, acc;
    static uint64_t seen;
    static int side = 1;
    float p[3];
    double at;
    uint64_t n;
    pthread_mutex_lock(&g_link_lock);
    memcpy(p, g_link, sizeof p), at = g_link_at, n = g_link_n;
    pthread_mutex_unlock(&g_link_lock);
    if (n == seen) return;
    double dt = at - lat;
    float dx = p[0] - lp[0], dy = p[1] - lp[1], dz = p[2] - lp[2], d = sqrtf(dx * dx + dz * dz);
    bool fresh = n != seen + 1 && (dt <= 0 || dt > 0.25);
    seen = n;
    memcpy(lp, p, sizeof lp), lat = at;
    if (fresh || dt <= 0 || dt > 0.25 || d > 2) { stride = 0; return; }  // (first sample, a pause, a warp)
    float v = d / (float)dt;
    spd += (fminf(v, 14) - spd) * 0.1f;  // (the samples' host times jitter: walking reads 4.5 +- 3)
    bool ground = fabsf(dy) / (float)dt < 0.8f;  // (not jumping / falling)
    static float dash_v = -1;
    if (dash_v < 0) dash_v = env_f("LARECOMP_SNOW_DASH", 6.5f);  // (world units / s: walking is 4.5, faster the boots)
    bool dash = spd > dash_v;
    static int logged;  // LARECOMP_LOG_SNOW: Link's speed (calibration)
    if (getenv("LARECOMP_LOG_SNOW") && logged++ % 20 == 0)
        LOG("[snow] link %.2f %.2f %.2f speed %.2f ground %d dash %d cover %.2f\n", p[0], p[1], p[2], spd, ground, dash, g_cover);
    if (!ground || d < 1e-4f || g_cover < 0.05f) { stride = 0; return; }
    float ux = dx / d, uz = dz / d;
    // a print every half stride, left and right of his path, along his way
    const float step = 0.5f, foot = 0.13f;
    float s0 = stride;
    stride += d;
    for (float k = step - s0; stride >= step && g_nprints < 64; k += step) {
        stride -= step;
        side = -side;
        float f = k / d;  // (where along this frame's move)
        SnowPrint *q = &g_prints[g_nprints++];
        q->x = p[0] - dx * (1 - f) - uz * foot * side, q->z = p[2] - dz * (1 - f) + ux * foot * side;
        q->y = p[1], q->t = (float)t;
        q->ang = atan2f(ux, uz), q->side = (float)side;
        q->len = dash ? 0.42f : 0.36f, q->wid = 0.19f;
    }
    // kicked-up snow: a few puffs a second walking, a stream with the boots
    if (g_cover < 0.15f || v < 0.6f) return;
    acc += dt * (dash ? 80 : 16) * fminf(g_cover * 1.5f, 1.0f);
    while (acc >= 1) acc -= 1, puff(p, ux, uz, dash);
}

int weather_snow_prints(SnowPrint *out, int max) {
    int n = g_nprints < max ? g_nprints : max;
    memcpy(out, g_prints, n * sizeof *out);
    g_nprints = 0;
    return n;
}

int weather_snow_puffs(SnowPuff out[SNOW_PUFFS]) {
    memcpy(out, g_puffs, sizeof g_puffs);
    return SNOW_PUFFS;
}

float weather_snow_now(void) { return (float)t; }
bool weather_snow_on(void) { return g_outdoors && g_cover > 0.002f; }

bool weather_snow_cover(SnowFrame *s, const float vp[16]) {
    static int dbg = -1;  // LARECOMP_SNOW_DEBUG=1 (test): the cover's mask in flat red
    if (dbg < 0) dbg = (int)env_f("LARECOMP_SNOW_DEBUG", 0);
    if (!g_outdoors || g_cover <= 0.002f) return false;
    memcpy(s->vp, vp, sizeof s->vp);
    if (!mat_inverse(s->vp, s->inv_vp)) return false;
    s->flags[2] = g_cover, s->flags[3] = (float)t;
    s->zr[2] = 32, s->zr[3] = 1024;  // (the trail map: 1024 texels over 32 units, ~3 cm each, wrapping)
    s->trail[0] = env_f("LARECOMP_SNOW_REFILL", 30), s->trail[1] = (float)dbg;
    // (the scene's colours are linear and before the game's tone mapping: its sunlit white ground is ~1)
    static float tone[4] = {-1};
    if (tone[0] < 0) {
        tone[0] = 0.84f, tone[1] = 0.87f, tone[2] = 0.93f, tone[3] = 0.8f;
        const char *e = getenv("LARECOMP_SNOW_TONE");  // r,g,b,ref (test)
        if (e) sscanf(e, "%f,%f,%f,%f", &tone[0], &tone[1], &tone[2], &tone[3]);
    }
    memcpy(s->tone, tone, sizeof tone);
    return true;
}

bool weather_frame(WeatherFrame *f, uint64_t frame, const float probe[WEATHER_PROBES]) {
    // host time, counted only while the overworld is on screen (a menu or a door stops it)
    static double last = 0;
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
    if (field && dt > 0 && dt < 0.25) {  // the snow on the ground: builds while it snows, melts otherwise
        static float build = -1;
        if (build < 0) build = env_f("LARECOMP_SNOW_BUILD", 90), g_cover = env_f("LARECOMP_SNOW_COVER", 0);  // (test)
        g_cover = kind == WEATHER_SNOW ? fminf(1, g_cover + (float)dt / build) : fmaxf(0, g_cover - (float)dt / 30);
    }
    if (!field || kind == WEATHER_OFF || g_cam_frame != frame) return false;
    if (dt > 0 && dt < 0.25) t += dt;
    if (kind == WEATHER_SNOW) snow_link();

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
