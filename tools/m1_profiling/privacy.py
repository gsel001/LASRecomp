"""Recursive typed allowlists for all shared JSON values. Unknown fields never pass through."""
import math
import re

# A schema node is a callable, dict, or a one-element list (bounded lists).
def clean(value,schema):
    if isinstance(schema,dict):
        source=value if isinstance(value,dict) else {}
        return {k:clean(source[k],spec) for k,spec in schema.items() if k in source}
    if isinstance(schema,list):
        return [clean(v,schema[0]) for v in value[:256]] if isinstance(value,list) else []
    return schema(value)
def enum(*allowed):return lambda x:x if type(x) is str and x in allowed else 'unverified'
def boolean(x):return x if type(x) is bool else False
def number(x):return x if type(x) in (int,float) and 0<=x<1e12 and math.isfinite(x) else None
def integer(x):return x if type(x) is int and 0<=x<10**12 else None
def digest(x):return x if isinstance(x,str) and re.fullmatch(r'[0-9a-f]{64}',x) else 'unverified'
def revision(x):return x if isinstance(x,str) and re.fullmatch(r'[0-9a-f]{40}',x) else 'unverified'
def stamp(x):return x if isinstance(x,str) and len(x)<=40 and re.fullmatch(r'\d{4}-\d\d-\d\dT[\d:.]+(?:Z|[+-]\d\d:\d\d)',x) else 'unverified'
def session(x):return x if isinstance(x,str) and re.fullmatch(r'\d{8}T\d{6}Z-(?:[ABC]|D[ABCK]|RT|RC|RI)-(baseline|experimental)-2880x1800-(overview|metal|frame|dynamic-log|dynamic-metal|dynamic-overview)-(stationary|movement|phased)-[0-9a-f]{8}',x) else 'unverified'
def branch(x):
    # Branch names are intentionally shared, but path-like/private/identifier-shaped inputs are rejected.
    return x if isinstance(x,str) and len(x)<=80 and re.fullmatch(r'(?:gsel001|codex)/[a-z][a-z0-9-]{0,63}',x) else 'unverified'
CODES=set('''capture_not_started missing_or_insufficient_runtime_samples level_changed_inside_window scene_changed_or_unconfirmed loading_or_focus_sized_gap shader_compilation_not_settled_or_unobservable render_scale_changed_in_recording_window invalid_runtime_row nonpositive_timing nonmonotonic_timestamps nonmonotonic_frames insufficient_time_coverage missing_runtime_periods graphics_settings_changed runtime_log_stale missing_proxy_intervals nonzero_game_exit trace_pid_unverified trace_toc_malformed trace_toc_missing trace_toc_incomplete trace_toc_unexpected trace_toc_pid_mismatch trace_export_failed recorder_interrupted recorder_timeout recorder_shutdown_unconfirmed recorder_failed analysis_failed Invalid OSError EOFError KeyboardInterrupt ValueError helper_drift session_failed'''.split())
def code(x):return x if isinstance(x,str) and x in CODES else 'unverified'
STAT={'samples':integer,'median':number,'p95':number,'method':enum('linear quantile; periodic blocks, not frames','linear quantile; explicitly selected samples'), 'status':enum('unavailable','unavailable; inspect Instruments','unavailable; inspect Instruments GPU timing','invalid evidence; distributions withheld')}
GRAPHICS={'fullscreen':boolean,'aspect':enum('original','unlocked'),'resolution':enum('match','1','dynamic'),'antialias':enum('off','smaa'),'dynamic':boolean,'upscaler':enum('metalfx','fsr1','bilinear','auto')}
OBSERVED={'drawable_observed':[integer],'render_scale_observed':[number],'render_area_derived_not_observed':[integer],
 'source_texture_dimensions':enum('unverified without frame capture'),'fullscreen_aspect_aa':enum('private requested settings and user confirmation; runtime state unverified'),
 'dynamic_resolution':enum('not requested; disabled in private settings; runtime enum unverified','selected privately and decision logs observed'),'status':enum('unverified')}
ENV={'model':lambda x:x if isinstance(x,str) and re.fullmatch(r'Mac(?:BookAir|BookPro|mini|Pro|Studio)?\d+,\d+',x) else 'unverified',
 'macos':lambda x:x if isinstance(x,str) and re.fullmatch(r'\d{1,2}\.\d{1,2}(?:\.\d{1,2})?',x) else 'unverified',
 'xcode':lambda x:x if isinstance(x,str) and re.fullmatch(r'Xcode \d+(?:\.\d+)*\nBuild version [A-Za-z0-9]{3,16}',x) else 'unverified',
 'instruments_version':lambda x:x if isinstance(x,str) and re.fullmatch(r'\d+(?:\.\d+)*',x) else 'unverified',
 'power_source':enum('AC','battery'),'battery_percent':lambda x:x if type(x) is int and 0<=x<=100 else None,
 'low_power_mode_by_source':{'Battery Power':integer,'AC Power':integer},
 'gpu_display_thermal':{'gpu':enum('Apple M1'),'thermal_state':lambda x:x if type(x) is int and x in range(4) else None,'display_points':[integer],'display_pixels':[integer]}}
RECORDING={'validation_utc':stamp,'request_to_validation_seconds':number,'trigger_phase':enum('intensive','baseline'),'requested_offset_seconds':number,'begin_utc':stamp,'end_utc':stamp,'requested_seconds':number,'requested_command_buffers':integer,'wall_seconds':number,'monotonic_seconds':number,
 'recorder_exit':lambda x:x if type(x) is int and -128<=x<=255 else None,'motion':enum('stationary','movement','phased'),
 'alignment':enum('recorder lifetime brackets; trim attach/start/stop margins in Instruments','trace request time; actual recording bounds require Instruments'),
 'shutdown':{'confirmed':boolean,'escalated':boolean,'stage':enum('already_exited','sigint','terminate','kill','unconfirmed'),'interrupts':integer}}
METRICS={k:STAT for k in ['runtime_fps_periodic','asynchronous_gpu_ms_per_present_proxy','cpu_frame_ms','gpu_execution_ms','present_interval_ms','individual_render_pass_ms']}
METRICS.update(errors=[code],status=enum('not recorded; dry-run only','partial command-buffer capture only; complete frame coverage/replay/counters unverified'),
 location_validation=enum('KeyCavern token matched when samples valid','Goponga requires user confirmation; only stable non-menu runtime level checked'),
 coverage={'rows':integer,'span_seconds':number,'required_seconds':number,'max_gap_seconds':number,'boundary_excluded':integer})
STATUS=enum('preparing','preflight_passed_not_launched','failed_or_interrupted','abnormal_game_exit','capture_requires_interval_review','capture_requires_trace_identity_review','capture_ready_for_manual_trace_review','captured_quality_pending','captured_invalid_runtime_window','launched_not_captured','finalization_failed','dynamic_observation_ready_for_review','dynamic_observation_requires_review')
SUMMARY={'build_selection':enum('baseline','beta6'),'beta6_upstream_commit':revision,'watchdog':{'enabled':boolean,'simulation_progress_available':boolean,'poll_seconds':number,'sample_seconds':number,'trace_seconds':number,'cooldown_seconds':number,'max_captures':integer,'prearmed':boolean},'visual_review_result':enum('none_reported','issue_reported','not_checked'),'observation_validated':boolean,'visual_check_complete':boolean,'dynamic_protocol':{'phase_seconds':number,'warmup_seconds':number,'guard_seconds':number,'log_poll_seconds':number,'log_dynres':boolean,'fps_interval_seconds':number,'hitch_threshold_ms':number},'dynamic_sources_sha256':{n:digest for n in ['dynamic_observe.py','dynamic_log.py']},'recovery_protocol':{'test':enum('screen-transition','combat','intensive'),'repeat_crossing':boolean,'recovery_seconds':number,'pace_details':boolean,'trace_seconds':number,'intensive_seconds':number,'trace_request_offset_seconds':number,'source_sha256':digest},'excluded_phases':[enum('stationary','movement','recovery','baseline','event_1','recovery_1','return_to_start','settle','event_2','recovery_2','intensive')],'schema':integer,'checked_utc':stamp,'session_id':session,'scenario':enum('A','B','C','DA','DB','DC','DK','RT','RC','RI'),'method':enum('overview','metal','frame','dynamic-log','dynamic-metal','dynamic-overview'),'renderer':enum('baseline','experimental'),
 'status':STATUS,'git_head':revision,'git_branch':branch,'git_dirty':boolean,'executable_sha256':digest,'library_sha256':digest,'helper_sha256':digest,'dependencies_manifest_sha256':digest,
 'profiling_sources_sha256':{k:digest for k in ['profile.py','analyze.py','isolation.py','privacy.py','tool_probe.m']},
 'requested_graphics':GRAPHICS,'motion':enum('stationary','movement','phased'),'expected_drawable':[integer],'observed':OBSERVED,
 'pid_executable_verified':boolean,'loaded_library_verified':boolean,'recording':RECORDING,'environment':ENV,'environment_end':ENV,'metrics':METRICS,
 'error_codes':[code],'trace_pid_verified':boolean,'capture_created':boolean,'capture_validated':boolean,'user_confirmed_graphics_and_scene':boolean,
 'capture_scope':enum('one command buffer; complete frame unverified','Instruments timeline','lightweight runtime log observation'),
 'workload':{'scene':enum('KeyCavern','Goponga','KanaletCastle'),'position':enum('historical-key-cavern-position','user-confirmed-goponga-position','upper-right-entrance'),'confirmation':boolean},
 'renderer_optimization':{'name':enum('LARECOMP_DEPTH_NO_FS'),'value':integer}}
# Warnings/instrumentation are fixed prose generated by the writer, never arbitrary input strings.
def summary(data):return clean(data,SUMMARY)
def metrics(data):return clean(data,METRICS)

REVIEW_SCHEMAS={
 'tests':{k:integer for k in ['tests_run','passed','failed','skipped','prior_tests','regression_tests','native_settings_cases']},
 'preservation':{'files_sha256_compared':integer,'all_match':boolean,'head':revision,'source_repo_written':boolean,'before_inventory_sha256':digest,'after_inventory_sha256':digest},
 'capabilities':{'synthetic_only':boolean,'no_game_launched':boolean,'compile_exit':integer,
  'templates':{k:{'record_exit':integer,'trace_exists':boolean,'toc_export_exit':integer,'target_pid_matches':boolean,'schema_count':integer,'relevant_schemas':[enum('metal-gpu-intervals','metal-application-command-buffer-submissions','metal-command-buffer-frame-assignment','metal-perf-overview-layer-per-frame-metric','metal-perf-overview-layer-per-frame-interval-metric')]} for k in ['game-performance-overview','game-performance','metal-system-trace']},
  'gpucapture':{'list_exit':integer,'boundaries_exit':integer,'capture_exit':integer,'capture_exists':boolean},'helper_device_metadata':ENV['gpu_display_thermal']}}
def review_record(kind,value):return clean(value,REVIEW_SCHEMAS[kind])
