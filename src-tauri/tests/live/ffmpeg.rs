//! Opt-in tests that drive a real ffmpeg/ffprobe from PATH on lavfi-generated
//! media. Included from `src/services/ffmpeg.rs` as a child module; run with
//! `cargo test -- --ignored`.

use super::*;
use crate::models::project::{Clip, ClipProperties, ProjectSettings, TextProperties, Track};

fn ffmpeg() -> PathBuf {
    PathBuf::from(if cfg!(windows) {
        "ffmpeg.exe"
    } else {
        "ffmpeg"
    })
}

fn ffprobe() -> PathBuf {
    PathBuf::from(if cfg!(windows) {
        "ffprobe.exe"
    } else {
        "ffprobe"
    })
}

fn test_settings(output: &Path) -> ExportSettings {
    ExportSettings {
        output_path: output.to_string_lossy().into_owned(),
        fps: 25,
        resolution: "original".into(),
        use_hardware_acceleration: false,
        ..Default::default()
    }
}

/// Render a 2 s 320x240 test pattern with a sine tone.
async fn make_clip(dir: &Path) -> PathBuf {
    let out = dir.join("in.mp4");
    let args: Vec<String> = [
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=size=320x240:rate=25:duration=2",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:duration=2",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
    ]
    .iter()
    .map(|s| s.to_string())
    .chain([file_arg(&out)])
    .collect();
    run_ffmpeg(&ffmpeg(), &args, "fixture").await.unwrap();
    path_policy::canonicalize(&out).unwrap()
}

fn project_with(source: &Path, text: &str) -> Project {
    let video = Clip {
        id: "c1".into(),
        track_id: "t1".into(),
        clip_type: ClipType::Video,
        name: "clip".into(),
        start_time: 0.0,
        end_time: 1.5,
        source_start: 0.0,
        source_end: 1.5,
        source_path: source.to_string_lossy().into_owned(),
        thumbnails: Vec::new(),
        properties: ClipProperties::default(),
    };
    let mut title = video.clone();
    title.id = "c2".into();
    title.clip_type = ClipType::Text;
    title.source_path = String::new();
    title.properties.text = Some(TextProperties {
        content: text.into(),
        font_family: "Arial".into(),
        font_size: 24,
        font_weight: 400,
        color: "#ffcc00".into(),
        background_color: "#000000".into(),
        align: TextAlign::Center,
        vertical_align: VerticalAlign::Bottom,
        ..Default::default()
    });
    let mk = |id: &str, track_type, clips| Track {
        id: id.into(),
        track_type,
        name: id.into(),
        clips,
        muted: false,
        locked: false,
        volume: 1.0,
        height: 80,
    };
    Project {
        id: "p".into(),
        name: "it".into(),
        created_at: String::new(),
        modified_at: String::new(),
        duration: 1.5,
        tracks: vec![
            mk("v", TrackType::Video, vec![video]),
            mk("t", TrackType::Text, vec![title]),
        ],
        settings: ProjectSettings {
            width: 320,
            height: 240,
            fps: 25,
            sample_rate: 48000,
        },
    }
}

#[tokio::test]
#[ignore = "needs ffmpeg and ffprobe on PATH"]
async fn probe_thumbnail_waveform_and_transcode() {
    let dir = tempfile::tempdir().unwrap();
    let input = make_clip(dir.path()).await;

    let meta = probe_with(&ffprobe(), &input).await.unwrap();
    assert_eq!((meta.width, meta.height), (320, 240));
    assert!(meta.has_audio);
    assert!((meta.duration - 2.0).abs() < 0.2);

    let thumb = dir.path().join("t.jpg");
    run_ffmpeg(
        &ffmpeg(),
        &build_thumbnail_args(&input, &thumb, 0.5, Some(160)),
        "thumb",
    )
    .await
    .unwrap();
    assert!(std::fs::metadata(&thumb).unwrap().len() > 0);

    let raw = run_ffmpeg(&ffmpeg(), &build_waveform_args(&input, 200), "wave")
        .await
        .unwrap();
    let wave = normalize_waveform(&raw);
    assert!(!wave.is_empty());
    assert!(wave.iter().all(|v| (0.0..=1.0).contains(v)));

    let out = dir.path().join("t.mkv");
    let s = ExportSettings {
        use_hardware_acceleration: false,
        ..Default::default()
    };
    let args = build_transcode_args(
        &input,
        &out,
        &s,
        &EncoderChoice {
            name: "libx264".into(),
            hardware: false,
        },
    );
    run_ffmpeg(&ffmpeg(), &args, "transcode").await.unwrap();
    assert!(probe_with(&ffprobe(), &out).await.unwrap().has_audio);
}

#[tokio::test]
#[ignore = "needs ffmpeg and ffprobe on PATH"]
async fn export_with_hostile_text_and_colors_renders() {
    let _guard = EXPORT_TEST_LOCK.lock().await;
    let dir = tempfile::tempdir().unwrap();
    let input = make_clip(dir.path()).await;
    let project = project_with(&input, "it's 100% a:b [x];movie=/etc/passwd %{pts}");
    let settings = ExportSettings {
        video_codec: "h264".into(),
        ..test_settings(&dir.path().join("out.mp4"))
    };

    let (tx, mut rx) = mpsc::channel(256);
    reset_export_cancel();
    let out = run_export(
        &ffmpeg(),
        &EncoderChoice {
            name: "libx264".into(),
            hardware: false,
        },
        &project,
        &settings,
        tx,
        true,
    )
    .await
    .unwrap();
    let meta = probe_with(&ffprobe(), &out).await.unwrap();
    assert_eq!((meta.width, meta.height), (320, 240));
    let mut last = None;
    while let Ok(p) = rx.try_recv() {
        last = Some(p.status);
    }
    assert_eq!(last, Some(ExportStatus::Completed));
}

#[tokio::test]
#[ignore = "needs ffmpeg on PATH"]
async fn cancel_stops_export_and_removes_output() {
    let _guard = EXPORT_TEST_LOCK.lock().await;
    let dir = tempfile::tempdir().unwrap();
    let input = make_clip(dir.path()).await;
    let mut project = project_with(&input, "slow");
    project.settings.width = 3840;
    project.settings.height = 2160;
    let settings = ExportSettings {
        encoding_preset: "veryslow".into(),
        ..test_settings(&dir.path().join("cancelled.mp4"))
    };
    let out_path = PathBuf::from(&settings.output_path);

    reset_export_cancel();
    let (tx, mut rx) = mpsc::channel(1024);
    let task = tokio::spawn(async move {
        run_export(
            &ffmpeg(),
            &EncoderChoice {
                name: "libx264".into(),
                hardware: false,
            },
            &project,
            &settings,
            tx,
            true,
        )
        .await
    });
    // Wait until ffmpeg is actually running before cancelling.
    while let Some(p) = rx.recv().await {
        if p.status == ExportStatus::Exporting {
            break;
        }
    }
    request_export_cancel();
    let err = task.await.unwrap().unwrap_err();
    assert!(matches!(err, AcevidsError::ExportFailed(_)), "{err:?}");
    assert!(!out_path.exists());
    assert!(!export_cancelled());
    let mut saw_cancelled = false;
    while let Ok(p) = rx.try_recv() {
        saw_cancelled |= p.status == ExportStatus::Cancelled;
    }
    assert!(saw_cancelled);
}

#[tokio::test]
#[ignore = "needs ffmpeg on PATH"]
async fn system_encoder_list_parses() {
    let raw = run_ffmpeg(
        &ffmpeg(),
        &["-hide_banner".to_string(), "-encoders".to_string()],
        "encoders",
    )
    .await
    .unwrap();
    let names = parse_encoder_list(&String::from_utf8_lossy(&raw));
    assert!(names.iter().any(|n| n == "aac"), "{names:?}");
    assert!(!names.iter().any(|n| n == "="));
}

/// Render `seconds` of test pattern to `name`. `audio` is an lavfi source for
/// the sound track (e.g. a sine tone, or `anullsrc` for digital silence), or
/// `None` for a file with no audio stream at all, like drone footage.
async fn make_source(dir: &Path, name: &str, seconds: u32, audio: Option<&str>) -> PathBuf {
    let out = dir.join(name);
    let mut args: Vec<String> = vec![
        "-y".into(),
        "-f".into(),
        "lavfi".into(),
        "-i".into(),
        format!("testsrc=size=320x240:rate=25:duration={seconds}"),
    ];
    if let Some(source) = audio {
        args.extend(["-f".into(), "lavfi".into(), "-i".into(), source.into()]);
        args.extend(["-c:a".into(), "aac".into(), "-shortest".into()]);
    }
    args.extend([
        "-c:v".into(),
        "libx264".into(),
        "-pix_fmt".into(),
        "yuv420p".into(),
        file_arg(&out),
    ]);
    run_ffmpeg(&ffmpeg(), &args, "fixture").await.unwrap();
    path_policy::canonicalize(&out).unwrap()
}

/// A clip of `kind` playing the first `length` seconds of `source` from
/// `start` on the timeline.
fn timeline_clip(kind: ClipType, source: &Path, start: f64, length: f64) -> Clip {
    Clip {
        id: format!("c{start}"),
        track_id: "t1".into(),
        clip_type: kind,
        name: "clip".into(),
        start_time: start,
        end_time: start + length,
        source_start: 0.0,
        source_end: length,
        source_path: source.to_string_lossy().into_owned(),
        thumbnails: Vec::new(),
        properties: ClipProperties::default(),
    }
}

fn project_of(clips: Vec<Clip>, duration: f64) -> Project {
    Project {
        id: "p".into(),
        name: "live".into(),
        created_at: String::new(),
        modified_at: String::new(),
        duration,
        tracks: vec![Track {
            id: "t1".into(),
            track_type: TrackType::Video,
            name: "Video".into(),
            clips,
            muted: false,
            locked: false,
            volume: 1.0,
            height: 80,
        }],
        settings: ProjectSettings {
            width: 320,
            height: 240,
            fps: 25,
            sample_rate: 48000,
        },
    }
}

fn software() -> EncoderChoice {
    EncoderChoice {
        name: "libx264".into(),
        hardware: false,
    }
}

/// Loudness (RMS, 0..1) of `seconds` of `file`'s audio starting at `from`.
async fn loudness(file: &Path, from: f64, seconds: f64) -> f64 {
    let args: Vec<String> = [
        "-v",
        "error",
        "-ss",
        &from.to_string(),
        "-t",
        &seconds.to_string(),
        "-i",
    ]
    .iter()
    .map(|s| s.to_string())
    .chain([file_arg(file)])
    .chain(
        ["-vn", "-ac", "1", "-f", "s16le", "-"]
            .iter()
            .map(|s| s.to_string()),
    )
    .collect();
    let pcm = run_ffmpeg(&ffmpeg(), &args, "loudness").await.unwrap();
    let samples: Vec<f64> = pcm
        .chunks_exact(2)
        .map(|b| f64::from(i16::from_le_bytes([b[0], b[1]])) / 32768.0)
        .collect();
    assert!(!samples.is_empty(), "no audio decoded from {file:?}");
    (samples.iter().map(|v| v * v).sum::<f64>() / samples.len() as f64).sqrt()
}

/// Duration in seconds of the first stream of `kind` ("v" or "a") in `file`.
async fn stream_seconds(file: &Path, kind: &str) -> f64 {
    let output = tokio_command(ffprobe())
        .args(["-v", "error", "-select_streams", &format!("{kind}:0")])
        .args(["-show_entries", "stream=duration", "-of", "csv=p=0"])
        .arg(file_arg(file))
        .output()
        .await
        .unwrap();
    String::from_utf8_lossy(&output.stdout)
        .trim()
        .parse()
        .unwrap()
}

#[tokio::test]
#[ignore = "needs ffmpeg and ffprobe on PATH"]
async fn silent_clip_gap_and_still_export_with_padded_sound() {
    let _guard = EXPORT_TEST_LOCK.lock().await;
    let dir = tempfile::tempdir().unwrap();
    let talk = make_source(
        dir.path(),
        "talk.mp4",
        2,
        Some("sine=frequency=440:duration=2"),
    )
    .await;
    let drone = make_source(dir.path(), "drone.mp4", 2, None).await;
    let still = dir.path().join("still.png");
    let args: Vec<String> = [
        "-y",
        "-f",
        "lavfi",
        "-i",
        "color=c=red:s=64x64",
        "-frames:v",
        "1",
    ]
    .iter()
    .map(|s| s.to_string())
    .chain([file_arg(&still)])
    .collect();
    run_ffmpeg(&ffmpeg(), &args, "still").await.unwrap();
    let still = path_policy::canonicalize(&still).unwrap();

    // 0-1.5 s talking, half a second of nothing, 2-4 s silent drone, 4-5 s still.
    let project = project_of(
        vec![
            timeline_clip(ClipType::Video, &talk, 0.0, 1.5),
            timeline_clip(ClipType::Video, &drone, 2.0, 2.0),
            timeline_clip(ClipType::Image, &still, 4.0, 1.0),
        ],
        5.0,
    );
    let settings = test_settings(&dir.path().join("mixed.mp4"));

    reset_export_cancel();
    let (tx, _rx) = mpsc::channel(1024);
    let out = run_export(&ffmpeg(), &software(), &project, &settings, tx, true)
        .await
        .unwrap();

    let video = stream_seconds(&out, "v").await;
    let audio = stream_seconds(&out, "a").await;
    assert!((video - 5.0).abs() < 0.1, "picture is {video} s");
    assert!((audio - 5.0).abs() < 0.15, "sound is {audio} s");
    // The tone is heard under the first clip and nowhere after it.
    assert!(loudness(&out, 0.2, 1.0).await > 0.01);
    assert!(loudness(&out, 2.5, 2.0).await < 0.001);
}

#[tokio::test]
#[ignore = "needs ffmpeg and ffprobe on PATH"]
async fn each_clip_is_heard_under_its_own_picture() {
    let _guard = EXPORT_TEST_LOCK.lock().await;
    let dir = tempfile::tempdir().unwrap();
    let quiet = make_source(
        dir.path(),
        "quiet.mp4",
        2,
        Some("anullsrc=r=48000:cl=stereo:d=2"),
    )
    .await;
    let tone = make_source(
        dir.path(),
        "tone.mp4",
        2,
        Some("sine=frequency=440:duration=2"),
    )
    .await;

    // Stored tone-first, but the quiet clip plays first on the timeline.
    let project = project_of(
        vec![
            timeline_clip(ClipType::Video, &tone, 2.0, 2.0),
            timeline_clip(ClipType::Video, &quiet, 0.0, 2.0),
        ],
        4.0,
    );
    let settings = test_settings(&dir.path().join("sequence.mp4"));

    reset_export_cancel();
    let (tx, _rx) = mpsc::channel(1024);
    let out = run_export(&ffmpeg(), &software(), &project, &settings, tx, true)
        .await
        .unwrap();

    assert!(
        loudness(&out, 0.2, 1.5).await < 0.001,
        "tone leaked into the first clip"
    );
    assert!(
        loudness(&out, 2.3, 1.5).await > 0.01,
        "tone missing from the second clip"
    );
}

#[tokio::test]
#[ignore = "needs ffmpeg and ffprobe on PATH"]
async fn unusable_hardware_encoder_falls_back_to_software() {
    let _guard = EXPORT_TEST_LOCK.lock().await;
    let dir = tempfile::tempdir().unwrap();
    let input = make_clip(dir.path()).await;
    let project = project_of(vec![timeline_clip(ClipType::Video, &input, 0.0, 1.0)], 1.0);
    let settings = test_settings(&dir.path().join("fallback.mp4"));

    // No ffmpeg build has this encoder, so the first attempt always fails.
    assert!(!encoder_works(&ffmpeg(), "h264_no_such_hardware").await);
    assert!(encoder_works(&ffmpeg(), "libx264").await);

    reset_export_cancel();
    let (tx, mut rx) = mpsc::channel(1024);
    let out = export_with_fallback(
        &ffmpeg(),
        EncoderChoice {
            name: "h264_no_such_hardware".into(),
            hardware: true,
        },
        &project,
        &settings,
        tx,
    )
    .await
    .unwrap();
    assert!(probe_with(&ffprobe(), &out).await.unwrap().duration > 0.9);
    let mut statuses = Vec::new();
    while let Ok(p) = rx.try_recv() {
        statuses.push(p.status);
    }
    assert!(!statuses.contains(&ExportStatus::Failed), "{statuses:?}");
    assert_eq!(statuses.last(), Some(&ExportStatus::Completed));
}

#[tokio::test]
#[ignore = "needs ffmpeg and ffprobe on PATH"]
async fn rotated_video_reports_its_display_size() {
    let dir = tempfile::tempdir().unwrap();
    let input = make_clip(dir.path()).await;
    let rotated = dir.path().join("rotated.mp4");
    let args: Vec<String> = ["-y", "-display_rotation:v:0", "90", "-i"]
        .iter()
        .map(|s| s.to_string())
        .chain([file_arg(&input)])
        .chain(["-c", "copy"].iter().map(|s| s.to_string()))
        .chain([file_arg(&rotated)])
        .collect();
    run_ffmpeg(&ffmpeg(), &args, "rotate").await.unwrap();

    let upright = probe_with(&ffprobe(), &input).await.unwrap();
    assert_eq!((upright.width, upright.height), (320, 240));
    let turned = probe_with(&ffprobe(), &rotated).await.unwrap();
    assert_eq!((turned.width, turned.height), (240, 320));
}
