// Weather (Cosmetics tab "Weather"): rain, snow or a thunderstorm drawn by the renderer over the game's 3D overworld,
// looks only (no effect on the game, its logic or a seed). The particles live in the world (they stay put as the
// camera scrolls) and are hidden behind whatever the scene's depth says is in front of them; rain splashes land where
// the depth says the ground is. Only on the overworld (level "Field") while it is on screen: not indoors, in dungeons,
// on the title or file select, nor behind the pause menu (the game draws no scene composite there).
//
// This file is the backend-neutral part: the setting, when it shows, the camera, the particle volume and the storm's
// flashes and thunder. A renderer calls weather_scene_camera() for its scene draws and weather_frame() right after
// the game's scene composite into the window image (the HUD comes after it), then draws with the WeatherFrame:
//   - streaks / flakes: `count` instances of 4 vertices (a strip), instance i at a hashed spot of the volume (WEATHER_SRC)
//   - splashes (rain, storm): `splashes` instances, each a ring on the ground at a hashed screen point, placed by the
//     scene depth there
//   - one full-screen triangle: rgb added, the picture multiplied by `keep` (overcast, lightning)
// Metal: runtime/nvn/renderer.m (weather_encode). Vulkan: not yet (the setting does nothing there).
#pragma once
#include <stdbool.h>
#include <stdint.h>

enum { WEATHER_OFF, WEATHER_RAIN, WEATHER_SNOW, WEATHER_STORM, WEATHER_RANDOM };

typedef struct {
    float vp[16];      // the scene camera's view-projection (rows, the game's GL clip space)
    float inv_vp[16];  // its inverse (rows)
    float origin[4];   // the volume's centre (world xyz), w unused
    float box[4];      // the volume's size across (x and z), its height, the time (s), the wind (world x per s)
    float shape[4];    // streak length (world), streak / flake width (pixels at 1080p), fall speed (world/s), sway (world)
    float color[4];    // the particles' colour (rgb, alpha)
    float screen[4];   // the target's content size in pixels (w, h), the depth's content size (w, h)
    float flags[4];    // x: flip y (window origin lower left), y: depth -1..1, z: mirrored, w: kind (1 rain, 2 snow)
    float fill[4];     // full-screen pass: rgb added (lightning), a = what the picture keeps (1 - overcast)
    float zr[4];       // the scene depth's range (the viewport's near, far - near; the renderer fills it)
    uint32_t count, splashes;  // instances
    int kind;          // WEATHER_RAIN / WEATHER_SNOW / WEATHER_STORM
} WeatherFrame;

// A scene draw's camera block (vertex constant slot 5, 320 bytes: view, projection, view-projection; perspective only)
// - the renderer passes every one; the frame's first is the camera. frame: the frame being translated.
void weather_scene_camera(const float *u, uint64_t size, uint64_t frame);
// After the frame's scene composite: what to draw (false: nothing - off, not outdoors, no camera this frame). The
// renderer fills screen, flags and zr first; probe: the scene depth at g_weather_probe_uv as the particle draw read it
// last frame (the ground's height; NULL: none yet) - written by its first vertex.
enum { WEATHER_PROBES = 5 };
extern const float g_weather_probe_uv[WEATHER_PROBES][2];
bool weather_frame(WeatherFrame *f, uint64_t frame, const float probe[WEATHER_PROBES]);
bool weather_probe_world(const WeatherFrame *f, int i, float d, float out[3]);
// The weather in effect now (WEATHER_OFF/RAIN/SNOW/STORM): the setting, its random roll, or the seed's own
int weather_current(void);
