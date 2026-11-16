import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";

const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }));
vi.mock("sonner", () => ({ toast }));

import { useEditorActions } from "@/components/editor/use-editor-actions";
import { useExportFlow } from "@/components/editor/use-export-flow";
import { useCaptionGeneration } from "@/components/editor/use-caption-generation";
import { useEditorShortcuts } from "@/components/editor/use-editor-shortcuts";
import { usePlaybackClock } from "@/components/editor/use-playback-clock";
import { useEditorStore } from "@/stores/editorStore";
import { emitBackendEvent, mockBackend } from "@/test/tauri";
import {
  allClips,
  currentProject,
  loadEditor,
  makeClip,
  makeProject,
  makeTrack,
} from "@/test/editor-fixtures";
import type { ExportDialogSettings } from "@/lib/editor/export";

function project() {
  return makeProject([
    makeTrack({ id: "tv", clips: [makeClip({ id: "v", startTime: 0, endTime: 10 })] }),
    makeTrack({
      id: "tl",
      type: "audio",
      locked: true,
      clips: [makeClip({ id: "l", type: "audio", startTime: 0, endTime: 5 })],
    }),
    makeTrack({ id: "tt", type: "text" }),
  ]);
}

beforeEach(() => {
  loadEditor(project());
  Object.values(toast).forEach((fn) => fn.mockReset());
});

describe("useEditorActions guards", () => {
  it("refuses to cut, duplicate, split or delete clips on locked tracks", async () => {
    const backend = mockBackend({ "plugin:dialog|ask": () => true });
    const { result } = renderHook(() => useEditorActions());
    act(() => result.current.cutClip("l"));
    act(() => result.current.duplicateClip("l"));
    act(() => useEditorStore.getState().seek(2));
    act(() => result.current.splitClip("l"));
    expect(toast.error).toHaveBeenCalledTimes(3);
    expect(toast.error).toHaveBeenCalledWith("Track is locked");
    await act(() => result.current.deleteClips(["l"]));
    expect(backend.callsTo("plugin:dialog|ask")).toHaveLength(0);
    expect(allClips()).toHaveLength(2);
  });

  it("ignores unknown clip ids", async () => {
    const { result } = renderHook(() => useEditorActions());
    act(() => {
      result.current.copyClip("nope");
      result.current.cutClip("nope");
      result.current.duplicateClip("nope");
      result.current.splitClip("nope");
    });
    await act(() => result.current.deleteClips(["nope"]));
    expect(toast.success).not.toHaveBeenCalled();
    expect(result.current.clipboard).toBeNull();
  });

  it("clip commands do nothing once the project is closed", () => {
    const { result } = renderHook(() => useEditorActions());
    loadEditor(null);
    act(() => result.current.cutClip("v"));
    expect(result.current.clipboard).toBeNull();
  });

  it("selection shortcuts need exactly one selected clip", () => {
    const { result } = renderHook(() => useEditorActions());
    act(() => result.current.copySelected());
    expect(result.current.clipboard).toBeNull();
    act(() => {
      useEditorStore.getState().selectClip("v");
      useEditorStore.getState().selectClip("l", true);
    });
    act(() => result.current.duplicateSelected());
    expect(allClips()).toHaveLength(2);
  });

  it("pastes onto the requested track, the selected track or the first compatible one", () => {
    const { result } = renderHook(() => useEditorActions());
    act(() => result.current.pasteClip());
    expect(allClips()).toHaveLength(2);

    act(() => result.current.copyClip("v"));
    const extra = useEditorStore.getState().addTrack("video");
    act(() => result.current.pasteClip(extra));
    expect(currentProject().tracks.find((t) => t.id === extra)!.clips).toHaveLength(1);

    act(() => useEditorStore.getState().selectTrack("tt"));
    act(() => result.current.pasteClip("tl"));
    expect(currentProject().tracks[0]!.clips).toHaveLength(2);
  });

  it("explains when no track can take the pasted clip", () => {
    const { result } = renderHook(() => useEditorActions());
    act(() => result.current.copyClip("l"));
    act(() => result.current.pasteClip());
    expect(toast.error).toHaveBeenCalledWith("No suitable track found");
  });

  it("requires a project for add, paste and save", async () => {
    mockBackend({
      get_video_metadata: () => ({ duration: 2, width: 640, height: 360, fps: 25 }),
    });
    const { result } = renderHook(() => useEditorActions());
    act(() => result.current.copyClip("v"));
    loadEditor(null);
    act(() => result.current.pasteClip());
    expect(result.current.addText()).toBeNull();
    await act(() =>
      result.current.addLibraryVideo({
        id: "x",
        title: "X",
        filePath: "/x.mp4",
        duration: 0,
      } as never)
    );
    expect(toast.error).toHaveBeenCalledWith("No project loaded");
    await act(() => result.current.saveProject());
    expect(toast.error).toHaveBeenCalledWith("Nothing to save yet");
  });

  it("library videos whose length cannot be read fall back to 60s", async () => {
    mockBackend({
      get_video_metadata: () => {
        throw "ffprobe failed";
      },
    });
    const { result } = renderHook(() => useEditorActions());
    await act(() =>
      result.current.addLibraryVideo({
        id: "x",
        title: "X",
        filePath: "/x.mp4",
        duration: 0,
      } as never)
    );
    expect(allClips().find((c) => c.name === "X")).toMatchObject({ startTime: 10, endTime: 70 });
  });

  it("library videos take their real length from the file", async () => {
    const backend = mockBackend({
      get_video_metadata: () => ({ duration: 4, width: 1512, height: 2688, fps: 59.94 }),
    });
    const { result } = renderHook(() => useEditorActions());
    const video = { id: "x", title: "Drone", filePath: "/drone.mp4", duration: 0 } as never;
    await act(() => result.current.addLibraryVideo(video));
    expect(backend.callsTo("get_video_metadata").map((c) => c.args.path)).toEqual(["/drone.mp4"]);
    expect(allClips().find((c) => c.name === "Drone")).toMatchObject({
      startTime: 10,
      endTime: 14,
    });
    // The timeline already has a picture, so the canvas is left alone.
    expect(currentProject().settings).toMatchObject({ width: 1920, height: 1080, fps: 30 });

    // A file that reports no length keeps the library's own value.
    backend.on("get_video_metadata", () => ({ duration: 0, width: 0, height: 0, fps: 0 }));
    const known = { id: "y", title: "Known", filePath: "/k.mp4", duration: 7 } as never;
    await act(() => result.current.addLibraryVideo(known));
    expect(allClips().find((c) => c.name === "Known")).toMatchObject({
      startTime: 14,
      endTime: 21,
    });
  });

  it("the first video on an empty timeline sets the project canvas", async () => {
    loadEditor(makeProject([makeTrack({ id: "tv" }), makeTrack({ id: "ta", type: "audio" })]));
    const backend = mockBackend({
      "plugin:dialog|open": () => ["/in/song.mp3", "/in/phone.mp4", "/in/wide.mp4"],
      get_video_metadata: (args) => {
        const path = String(args.path);
        if (path.endsWith(".mp3")) return { duration: 3, width: 0, height: 0, fps: 0 };
        return path.includes("phone")
          ? { duration: 6, width: 1081, height: 1920, fps: 60 }
          : { duration: 5, width: 3840, height: 2160, fps: 24 };
      },
    });
    const { result } = renderHook(() => useEditorActions());
    await act(() => result.current.importFiles());
    // The vertical phone clip came first, so the project is vertical at 60 fps.
    expect(currentProject().settings).toMatchObject({ width: 1080, height: 1920, fps: 60 });
    expect(useEditorStore.getState().isDirty).toBe(true);

    // Later videos do not reshape a project that already has a picture.
    backend.on("plugin:dialog|open", () => "/in/wide.mp4");
    await act(() => result.current.importFiles());
    expect(currentProject().settings).toMatchObject({ width: 1080, height: 1920, fps: 60 });

    // A still already on the timeline counts as a picture too.
    loadEditor(
      makeProject([
        makeTrack({
          id: "tv",
          clips: [makeClip({ id: "logo", type: "image", startTime: 0, endTime: 5 })],
        }),
      ])
    );
    backend.on("plugin:dialog|open", () => "/in/phone.mp4");
    await act(() => result.current.importFiles());
    expect(currentProject().settings).toMatchObject({ width: 1920, height: 1080, fps: 30 });
  });

  it("undoing the first import restores the canvas it replaced", async () => {
    loadEditor(makeProject([makeTrack({ id: "tv" })]));
    mockBackend({
      "plugin:dialog|open": () => "/in/phone.mp4",
      get_video_metadata: () => ({ duration: 6, width: 1080, height: 1920, fps: 60 }),
    });
    const { result } = renderHook(() => useEditorActions());
    await act(() => result.current.importFiles());
    expect(currentProject().settings).toMatchObject({ width: 1080, height: 1920, fps: 60 });

    act(() => useEditorStore.getState().undo());
    expect(allClips()).toHaveLength(0);
    expect(currentProject().settings).toMatchObject({ width: 1920, height: 1080, fps: 30 });
  });

  it("import exits quietly when the dialog is cancelled", async () => {
    const backend = mockBackend({ "plugin:dialog|open": () => null });
    const { result } = renderHook(() => useEditorActions());
    await act(() => result.current.importFiles());
    expect(backend.callsTo("get_video_metadata")).toHaveLength(0);
    expect(toast.success).not.toHaveBeenCalled();
  });

  it("import of only unsupported files adds nothing", async () => {
    mockBackend({ "plugin:dialog|open": () => "C:\\readme.md" });
    const { result } = renderHook(() => useEditorActions());
    await act(() => result.current.importFiles());
    expect(allClips()).toHaveLength(2);
    expect(toast.success).not.toHaveBeenCalled();
  });
});

describe("useExportFlow", () => {
  const settings: ExportDialogSettings = {
    format: "mp4",
    videoCodec: "h264",
    audioCodec: "aac",
    audioBitrate: "192",
    resolution: "original",
    frameRate: "original",
    crfQuality: 23,
    encodingPreset: "medium",
    hardwareAcceleration: true,
    hardwareAccelerationType: "auto",
    outputPath: "C:\\o.mp4",
  };

  it("requires an output path and a project", async () => {
    const backend = mockBackend();
    const { result } = renderHook(() => useExportFlow());
    await act(() => result.current.startExport({ ...settings, outputPath: "" }));
    loadEditor(null);
    await act(() => result.current.startExport(settings));
    expect(toast.error).toHaveBeenCalledTimes(2);
    expect(backend.callsTo("export_project")).toHaveLength(0);
  });

  it("reports the output path when the command resolves first", async () => {
    mockBackend({ export_project: () => "C:\\final.mp4" });
    const onFinished = vi.fn();
    const { result } = renderHook(() => useExportFlow(onFinished));
    await act(() => result.current.startExport(settings));
    expect(toast.success).toHaveBeenCalledWith("Export complete: C:\\final.mp4");
    expect(onFinished).toHaveBeenCalled();
    await emitBackendEvent("export-progress", { status: "completed", progress: 100, error: null });
    expect(toast.success).toHaveBeenCalledTimes(1);
  });

  it("falls back to a generic message for failures without details", async () => {
    let fail!: (e: unknown) => void;
    mockBackend({ export_project: () => new Promise((_, r) => (fail = r)) });
    const { result } = renderHook(() => useExportFlow());
    let pending!: Promise<void>;
    act(() => {
      pending = result.current.startExport(settings);
    });
    await emitBackendEvent("export-progress", { status: "failed", progress: 0, error: null });
    expect(toast.error).toHaveBeenCalledWith("Export failed: Unknown error");
    await act(async () => {
      fail("boom");
      await pending;
    });
    expect(toast.error).toHaveBeenCalledTimes(1);
  });

  it("shows the reason carried by a backend error object", async () => {
    mockBackend({
      export_project: () => {
        throw { code: "FFMPEG_ERROR", message: "FFmpeg error: Cannot load libcuda.so.1" };
      },
    });
    const { result } = renderHook(() => useExportFlow());
    await act(() => result.current.startExport(settings));
    expect(toast.error).toHaveBeenCalledWith(
      "Export failed: FFmpeg error: Cannot load libcuda.so.1"
    );
  });

  it("reports a failed cancel", async () => {
    mockBackend({
      cancel_export: () => {
        throw "no export running";
      },
    });
    const { result } = renderHook(() => useExportFlow());
    await act(() => result.current.cancelExport());
    expect(toast.error).toHaveBeenCalledWith("Failed to cancel export");
  });
});

describe("useCaptionGeneration", () => {
  it("needs a video clip", async () => {
    const backend = mockBackend();
    loadEditor(makeProject([makeTrack({ type: "audio" })]));
    const { result } = renderHook(() => useCaptionGeneration());
    await act(() => result.current.generate({ model: "tiny.en", styleId: "clean" }));
    expect(toast.error).toHaveBeenCalledWith("Add a video to the timeline first");
    expect(backend.callsTo("generate_captions")).toHaveLength(0);
  });

  it("shows the message of an Error thrown by the backend", async () => {
    mockBackend({
      generate_captions: () => {
        throw new Error("whisper crashed");
      },
    });
    const { result } = renderHook(() => useCaptionGeneration());
    await act(() => result.current.generate({ model: "tiny.en", styleId: "clean" }));
    expect(toast.error).toHaveBeenCalledWith(expect.stringContaining("Caption generation failed"));
    expect(result.current.generating).toBe(false);
  });

  it("treats negative progress as indeterminate", async () => {
    mockBackend();
    const { result } = renderHook(() => useCaptionGeneration());
    await waitFor(async () => {
      await emitBackendEvent("caption-progress", {
        stage: "download",
        progress: -1,
        message: "Downloading",
      });
      expect(result.current.stage).toBe("Downloading");
    });
    expect(result.current.progress).toBeNull();
  });
});

describe("useEditorShortcuts", () => {
  it("skips events already handled elsewhere and keys without a handler", () => {
    const undo = vi.fn();
    renderHook(() => useEditorShortcuts({ undo }));
    const handled = new KeyboardEvent("keydown", { key: "z", ctrlKey: true, cancelable: true });
    handled.preventDefault();
    window.dispatchEvent(handled);
    expect(undo).not.toHaveBeenCalled();

    const unbound = new KeyboardEvent("keydown", { key: " ", cancelable: true });
    window.dispatchEvent(unbound);
    expect(unbound.defaultPrevented).toBe(false);

    const notAShortcut = new KeyboardEvent("keydown", { key: "q", cancelable: true });
    window.dispatchEvent(notAShortcut);
    expect(notAShortcut.defaultPrevented).toBe(false);

    window.dispatchEvent(new KeyboardEvent("keydown", { key: "z", ctrlKey: true }));
    expect(undo).toHaveBeenCalledTimes(1);
  });
});

describe("usePlaybackClock", () => {
  it("a frame that fires after playback stopped does nothing", () => {
    const frames: FrameRequestCallback[] = [];
    vi.spyOn(window, "requestAnimationFrame").mockImplementation((cb) => {
      frames.push(cb);
      return frames.length;
    });
    vi.spyOn(window, "cancelAnimationFrame").mockImplementation(() => {});
    renderHook(() => usePlaybackClock());
    act(() => useEditorStore.getState().play());
    act(() => useEditorStore.getState().pause());
    act(() => frames[0]!(performance.now() + 1000));
    expect(useEditorStore.getState().currentTime).toBe(0);
    expect(frames).toHaveLength(1);
    vi.restoreAllMocks();
  });
});
